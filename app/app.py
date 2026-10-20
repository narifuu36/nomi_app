from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_mail import Mail, Message
import sqlite3
import requests
import hashlib
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

app = Flask(__name__)
app.secret_key = "nomitomo-secret-2026"

# ==========================
# DBパスの絶対パス設定
# ==========================
BASE_DIR = Path(__file__).resolve().parent
DB_NAME = str(BASE_DIR / "nomikai.db")
HOTPEPPER_API_KEY = "50476680ea3687f7"

# ==========================
# メール送信設定 (Gmail SMTP)
# ==========================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'nomitomo.service@gmail.com'
app.config['MAIL_PASSWORD'] = 'svioicmeomsyvrqn'
app.config['MAIL_DEFAULT_SENDER'] = ('のみとも', 'nomitomo.service@gmail.com')

mail = Mail(app)


# ==========================
# DB接続＆テーブル・カラム自動作成
# ==========================

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """テーブルおよびリマインド用カラムが存在しない場合に自動生成する"""
    conn = get_db()
    
    # テーブル自動作成
    conn.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT,
        password_hash TEXT NOT NULL
    )
    ''')
    
    conn.execute('''
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        host_user_id INTEGER NOT NULL,
        places TEXT,
        dates TEXT,
        times TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        finished_at TIMESTAMP,
        remind_close_sent INTEGER DEFAULT 0,
        remind_day_sent INTEGER DEFAULT 0,
        final_date TEXT
    )
    ''')
    
    conn.execute('''
    CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        is_join INTEGER NOT NULL,
        place TEXT,
        date TEXT,
        time_slot TEXT
    )
    ''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS billings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        total_amount INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    )
    ''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS billing_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        billing_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        base_amount INTEGER NOT NULL,
        adjustment INTEGER NOT NULL DEFAULT 0,
        final_amount INTEGER NOT NULL,
        discount_enabled INTEGER NOT NULL DEFAULT 0
    )
    ''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS standalone_billings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL DEFAULT '',
        total_amount INTEGER NOT NULL,
        created_by_user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    )
    ''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS standalone_billing_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        billing_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        base_amount INTEGER NOT NULL,
        adjustment INTEGER NOT NULL DEFAULT 0,
        final_amount INTEGER NOT NULL,
        discount_enabled INTEGER NOT NULL DEFAULT 0
    )
    ''')

    # カラム追加（既存DB用）
    try:
        conn.execute("ALTER TABLE events ADD COLUMN remind_close_sent INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE events ADD COLUMN remind_day_sent INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE events ADD COLUMN final_date TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


# アプリ起動時にDBの自動初期化を実行
init_db()


# ==========================
# ログイン確認
# ==========================

def login_required():
    return "username" in session


# ==========================
# イベント集計ヘルパー関数
# ==========================

def get_event_summary_text(conn, event_id):
    """イベントの集計結果テキストと参加者メールアドレス一覧を返す"""
    votes = conn.execute("""
        SELECT votes.*, users.username, users.email
        FROM votes
        JOIN users ON votes.user_id = users.id
        WHERE votes.event_id = ?
    """, (event_id,)).fetchall()

    participants = []
    participant_emails = []

    place_counter = Counter()
    date_counter = Counter()
    time_counter = Counter()

    for vote in votes:
        if vote["is_join"]:
            participants.append(vote["username"])
            if vote["email"]:
                participant_emails.append(vote["email"])

            if vote["place"]:
                for p in vote["place"].split(","):
                    if p:
                        place_counter[p] += 1
            if vote["date"]:
                for d in vote["date"].split(","):
                    if d:
                        date_counter[d] += 1
            if vote["time_slot"]:
                for t in vote["time_slot"].split(","):
                    if t:
                        time_counter[t] += 1

    top_date = f"{date_counter.most_common(1)[0][0]} ({date_counter.most_common(1)[0][1]}票)" if date_counter else "未集計"
    top_time = f"{time_counter.most_common(1)[0][0]} ({time_counter.most_common(1)[0][1]}票)" if time_counter else "未集計"
    top_place = f"{place_counter.most_common(1)[0][0]} ({place_counter.most_common(1)[0][1]}票)" if place_counter else "未集計"

    members_str = "\n".join([f"・{name}" for name in participants]) if participants else "参加者なし"

    summary_text = (
        f"----------------------------------------\n"
        f"🏆 一番人気の条件\n"
        f"📅 日付：{top_date}\n"
        f"⏰ 時間：{top_time}\n"
        f"📍 場所：{top_place}\n\n"
        f"👥 参加メンバー ({len(participants)}名)\n"
        f"{members_str}\n"
        f"----------------------------------------"
    )

    return summary_text, list(set(participant_emails))


# ==========================
# イベント自動終了＆リマインド処理
# ==========================

def auto_close_event():

    conn = get_db()

    event = conn.execute("""
        SELECT *
        FROM events
        WHERE is_active = 1
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()

    if event:

        created = datetime.strptime(
            event["created_at"],
            "%Y-%m-%d %H:%M:%S"
        )

        now = datetime.now()
        end_time = created + timedelta(hours=24)
        remind_time = created + timedelta(hours=21)  # 残り3時間

        # --------------------------
        # 1. 締め切り3時間前リマインド (未投票者宛て)
        # --------------------------
        if now >= remind_time and now < end_time and event["remind_close_sent"] == 0:
            unvoted_users = conn.execute("""
                SELECT email
                FROM users
                WHERE email IS NOT NULL AND email != ''
                AND id NOT IN (
                    SELECT user_id FROM votes WHERE event_id = ?
                )
            """, (event["id"],)).fetchall()

            emails = [u["email"] for u in unvoted_users]

            if emails:
                try:
                    msg = Message(
                        subject=f"【あと3時間⏰】飲み会「{event['title']}」の回答忘れてないー？",
                        bcc=emails,  # ★ BCCに変更
                        body=(
                            f"やっほー！飲み会「{event['title']}」の調整中だよ🍻\n\n"
                            f"募集の締め切りまであと【3時間】になりました！\n"
                            f"まだ投票してないみたいだから、行ける日と場所をサクッと教えてね！\n"
                            f"（不参加の場合もポチッと投票してもらえると助かる〜！）\n\n"
                            f"▼ アプリで投票する\n"
                            f"http://127.0.0.1:5000/"
                        )
                    )
                    mail.send(msg)
                except Exception as e:
                    app.logger.error(f"締め切りリマインド送信エラー: {e}")

            conn.execute("UPDATE events SET remind_close_sent = 1 WHERE id = ?", (event["id"],))
            conn.commit()

        # --------------------------
        # 2. 自動終了処理 (24時間経過)
        # --------------------------
        if now >= end_time:

            summary_text, emails = get_event_summary_text(conn, event["id"])

            conn.execute("""
                UPDATE events
                SET
                    is_active = 0,
                    finished_at = CURRENT_TIMESTAMP
                WHERE id=?
            """, (event["id"],))

            conn.commit()

            if emails:
                try:
                    msg = Message(
                        subject=f"【自動終了】飲み会「{event['title']}」の募集期間が終了したよ！",
                        bcc=emails,  # ★ BCCに変更
                        body=(
                            f"「{event['title']}」の募集期限（24時間）が過ぎたから自動的に締め切られたよ！\n\n"
                            f"【集計結果】\n"
                            f"{summary_text}\n\n"
                            f"アプリで詳細を確認してね👇\n"
                            f"http://127.0.0.1:5000/"
                        )
                    )
                    mail.send(msg)
                except Exception as e:
                    app.logger.error(f"自動クローズメール送信エラー: {e}")

    # --------------------------
    # 3. 開催当日の朝リマインド (確定済みイベント)
    # --------------------------
    finished_events = conn.execute("""
        SELECT * FROM events
        WHERE is_active = 0 AND final_date IS NOT NULL AND remind_day_sent = 0
    """).fetchall()

    today_str = datetime.now().strftime("%Y-%m-%d")

    for fevent in finished_events:
        if fevent["final_date"] == today_str:
            _, emails = get_event_summary_text(conn, fevent["id"])

            if emails:
                try:
                    msg = Message(
                        subject=f"【今日だよ！🍻】飲み会「{fevent['title']}」楽しんでいこー！",
                        bcc=emails,  # ★ BCCに変更
                        body=(
                            f"おはよう！今日は待ちに待った飲み会「{fevent['title']}」の日だよ🎉\n\n"
                            f"遅れそうな時とかは、早めに連絡してね！\n"
                            f"それじゃあ、あとで楽しもう〜👋"
                        )
                    )
                    mail.send(msg)
                except Exception as e:
                    app.logger.error(f"当日リマインド送信エラー: {e}")

            conn.execute("UPDATE events SET remind_day_sent = 1 WHERE id = ?", (fevent["id"],))
            conn.commit()

    conn.close()


# ==========================
# TOP
# ==========================

@app.route("/")
def home():

    auto_close_event()

    if not login_required():
        return redirect(url_for("login"))

    return redirect(url_for("index"))


# ==========================
# INDEX
# ==========================

@app.route("/index")
def index():

    auto_close_event()

    if not login_required():
        return redirect(url_for("login"))

    conn = get_db()

    event = conn.execute(
        """
        SELECT
            events.*,
            users.username AS host_name
        FROM events
        JOIN users
        ON events.host_user_id = users.id
        WHERE is_active = 1
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    conn.close()

    return render_template(
        "index.html",
        username=session["username"],
        event_exists=(event is not None),
        event=event
    )


# ==========================
# LOGIN
# ==========================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        password_hash = hashlib.sha256(
            password.encode()
        ).hexdigest()

        conn = get_db()

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username = ?
            AND password_hash = ?
            """,
            (
                username,
                password_hash
            )
        ).fetchone()

        conn.close()

        if user:

            session["username"] = user["username"]

            flash("ログインしました")

            return redirect(url_for("index"))

        return render_template(
            "login.html",
            error="ユーザー名またはパスワードが違います"
        )

    return render_template(
        "login.html",
        registered=request.args.get("registered"),
        reset=request.args.get("reset")
    )


# ==========================
# SIGNUP
# ==========================

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        username = request.form["username"].strip()
        password = request.form["password"]
        password_confirm = request.form["password_confirm"]
        email = request.form["email"].strip()

        if password != password_confirm:

            return render_template(
                "signup.html",
                error="パスワードが一致しません"
            )

        password_hash = hashlib.sha256(
            password.encode()
        ).hexdigest()

        conn = get_db()

        exists = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username = ? OR email = ?
            """,
            (username, email)
        ).fetchone()

        if exists:

            conn.close()

            return render_template(
                "signup.html",
                error="そのユーザー名またはメールアドレスは既に使用されています"
            )

        conn.execute(
            """
            INSERT INTO users
            (
                username,
                email,
                password_hash
            )
            VALUES
            (
                ?, ?, ?
            )
            """,
            (
                username,
                email,
                password_hash
            )
        )

        conn.commit()
        conn.close()

        return redirect(
            url_for(
                "login",
                registered=1
            )
        )

    return render_template(
        "signup.html"
    )


# ==========================
# CREATE EVENT
# ==========================

@app.route("/create_event", methods=["GET", "POST"])
def create_event():

    auto_close_event()

    if not login_required():
        return redirect(url_for("login"))

    conn = get_db()

    active_event = conn.execute(
        """
        SELECT *
        FROM events
        WHERE is_active = 1
        LIMIT 1
        """
    ).fetchone()

    if active_event:

        conn.close()

        flash("現在募集中のイベントがあります。")

        return redirect(url_for("event"))

    if request.method == "POST":

        title = request.form["title"]

        places = request.form.get("all_places", "")
        dates = request.form.get("all_dates", "")
        times = request.form.get("all_times", "")

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username=?
            """,
            (session["username"],)
        ).fetchone()

        conn.execute(
            """
            INSERT INTO events
            (
                title,
                host_user_id,
                places,
                dates,
                times
            )
            VALUES
            (
                ?, ?, ?, ?, ?
            )
            """,
            (
                title,
                user["id"],
                places,
                dates,
                times
            )
        )

        conn.commit()

        # 新規作成時に他メンバーへメール送信
        other_users = conn.execute(
            """
            SELECT email
            FROM users
            WHERE email IS NOT NULL AND email != '' AND id != ?
            """,
            (user["id"],)
        ).fetchall()

        emails = [u["email"] for u in other_users]

        conn.close()

        if emails:
            try:
                msg = Message(
                    subject=f"【新規募集】{session['username']}さんが飲み会「{title}」を作成したよ！",
                    bcc=emails,  # ★ BCCに変更
                    body=(
                        f"{session['username']}さんが新しい飲み会「{title}」の募集を開始したよ！\n"
                        f"日程や場所の希望をアプリから投票してね👇\n\n"
                        f"http://127.0.0.1:5000/"
                    )
                )
                mail.send(msg)
            except Exception as e:
                app.logger.error(f"イベント作成通知メール送信エラー: {e}")

        flash("イベントを作成しました")

        return redirect(url_for("event"))

    conn.close()

    return render_template(
        "create_event.html"
    )


# ==========================
# EVENT
# ==========================

@app.route("/event", methods=["GET", "POST"])
def event():

    auto_close_event()

    if not login_required():
        return redirect(url_for("login"))

    conn = get_db()

    event = conn.execute(
        """
        SELECT
            events.*,
            users.username AS host_name
        FROM events
        JOIN users
        ON events.host_user_id = users.id
        WHERE events.is_active = 1
        ORDER BY events.id DESC
        LIMIT 1
        """
    ).fetchone()

    if event is None:

        conn.close()

        return redirect(url_for("create_event"))

    created = datetime.strptime(
        event["created_at"],
        "%Y-%m-%d %H:%M:%S"
    )

    end_time = created + timedelta(hours=24)

    remain = end_time - datetime.now()

    if remain.total_seconds() < 0:
        remain = timedelta(seconds=0)

    hours = remain.seconds // 3600
    minutes = (remain.seconds % 3600) // 60

    if request.method == "POST":

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username=?
            """,
            (session["username"],)
        ).fetchone()

        already = conn.execute(
            """
            SELECT *
            FROM votes
            WHERE event_id=?
            AND user_id=?
            """,
            (
                event["id"],
                user["id"]
            )
        ).fetchone()

        if already:

            conn.execute(
                """
                DELETE FROM votes
                WHERE id=?
                """,
                (already["id"],)
            )

        conn.execute(
            """
            INSERT INTO votes
            (
                event_id,
                user_id,
                is_join,
                place,
                date,
                time_slot
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event["id"],
                user["id"],
                int(request.form["will_join"]),
                ",".join(request.form.getlist("place")),
                ",".join(request.form.getlist("date")),
                ",".join(request.form.getlist("time_slot"))
            )
        )

        conn.commit()
        conn.close()

        return redirect(
            url_for(
                "result",
                voted=1
            )
        )

    conn.close()

    return render_template(
        "event.html",
        username=session["username"],
        event=event,
        host_name=event["host_name"],
        remain_hours=hours,
        remain_minutes=minutes,
        places=event["places"].split(",") if event["places"] else [],
        dates=event["dates"].split(",") if event["dates"] else [],
        times=event["times"].split(",") if event["times"] else []
    )


# ==========================
# HOTPEPPER SEARCH
# ==========================

@app.route("/hotpepper/search")
def hotpepper_search():
    keyword = request.args.get("keyword", "").strip()
    genre = request.args.get("genre", "").strip()
    budget = request.args.get("budget", "").strip()
    private_room = request.args.get("private_room", "0")
    free_drink = request.args.get("free_drink", "0")

    if not keyword:
        return jsonify({"shops": []})

    params = {
        "key": HOTPEPPER_API_KEY,
        "keyword": keyword,
        "format": "json",
        "count": 30,
        "private_room": "1" if private_room == "1" else "0",
        "free_drink": "1" if free_drink == "1" else "0"
    }

    if genre:
        params["genre"] = genre

    if budget:
        params["budget"] = budget

    url = "http://webservice.recruit.co.jp/hotpepper/gourmet/v1/"

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        shops = data.get("results", {}).get("shop", [])
        results = []

        for shop in shops:
            results.append({
                "name": shop.get("name", ""),
                "address": shop.get("address", ""),
                "genre": shop.get("genre", {}).get("name", ""),
                "budget": shop.get("budget", {}).get("name", ""),
                "station": shop.get("station_name", ""),
                "url": shop.get("urls", {}).get("pc", ""),
                "phone": shop.get("tel", ""),
                "open": shop.get("open", ""),
                "close": shop.get("close", ""),
                "access": shop.get("access", ""),
                "catch": shop.get("catch", ""),
                "capacity": shop.get("capacity", ""),
                "parking": shop.get("parking", ""),
                "private_room": shop.get("private_room", ""),
                "free_drink": shop.get("free_drink", ""),
                "lat": shop.get("lat", ""),
                "lng": shop.get("lng", "")
            })

        return jsonify({"shops": results})

    except requests.exceptions.Timeout:
        app.logger.warning("HotPepper API timeout")
        return jsonify({"error": "店舗検索がタイムアウトしました"}), 504

    except requests.exceptions.RequestException:
        app.logger.exception("HotPepper API request failed")
        return jsonify({"error": "店舗情報の取得に失敗しました"}), 502

    except ValueError:
        app.logger.exception("HotPepper API JSON parsing failed")
        return jsonify({"error": "店舗情報を正しく読み込めませんでした"}), 502


# ==========================
# RESULT
# ==========================

@app.route("/result")
def result():

    auto_close_event()

    if not login_required():
        return redirect(url_for("login"))

    conn = get_db()

    event = conn.execute(
        """
        SELECT
            events.*,
            users.username AS host_name
        FROM events
        JOIN users
        ON events.host_user_id = users.id
        WHERE events.is_active = 1
        ORDER BY events.id DESC
        LIMIT 1
        """
    ).fetchone()

    if event is None:

        conn.close()

        return redirect(url_for("index"))

    votes = conn.execute(
        """
        SELECT
            votes.*,
            users.username
        FROM votes
        JOIN users
        ON votes.user_id = users.id
        WHERE votes.event_id = ?
        """,
        (event["id"],)
    ).fetchall()

    participants = []

    place_counter = Counter()
    date_counter = Counter()
    time_counter = Counter()

    for vote in votes:

        if vote["is_join"]:
            participants.append(vote["username"])

        if vote["place"]:
            for p in vote["place"].split(","):
                if p:
                    place_counter[p] += 1

        if vote["date"]:
            for d in vote["date"].split(","):
                if d:
                    date_counter[d] += 1

        if vote["time_slot"]:
            for t in vote["time_slot"].split(","):
                if t:
                    time_counter[t] += 1

    created = datetime.strptime(
        event["created_at"],
        "%Y-%m-%d %H:%M:%S"
    )

    end_time = created + timedelta(hours=24)

    remain = end_time - datetime.now()

    if remain.total_seconds() < 0:
        remain = timedelta(seconds=0)

    hours = remain.seconds // 3600
    minutes = (remain.seconds % 3600) // 60

    is_host = (
        session["username"] ==
        event["host_name"]
    )

    conn.close()

    return render_template(
        "result.html",
        username=session["username"],
        event=event,
        host_name=event["host_name"],
        participants=participants,
        place_results=place_counter.items(),
        date_results=date_counter.items(),
        time_results=time_counter.items(),
        voted=request.args.get("voted"),
        is_host=is_host
    )


# ==========================
# COMPLETE (手動終了)
# ==========================

@app.route("/complete")
def complete():

    if not login_required():
        return redirect(url_for("login"))

    conn = get_db()

    event = conn.execute(
        """
        SELECT
            events.*,
            users.username AS host_name
        FROM events
        JOIN users
        ON events.host_user_id = users.id
        WHERE is_active=1
        LIMIT 1
        """
    ).fetchone()

    if event is None:

        conn.close()

        return redirect(url_for("index"))

    if event["host_name"] != session["username"]:

        conn.close()

        flash("主催者のみ終了できます")

        return redirect(url_for("result"))

    summary_text, emails = get_event_summary_text(conn, event["id"])

    conn.execute(
        """
        UPDATE events
        SET
            is_active=0,
            finished_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (event["id"],)
    )

    conn.commit()
    conn.close()

    if emails:
        try:
            msg = Message(
                subject=f"【決定】飲み会「{event['title']}」の日程・詳細が決まったよ！",
                bcc=emails,  # ★ BCCに変更
                body=(
                    f"「{event['title']}」の募集が主催者によって締め切られたよ！\n"
                    f"みんなの希望を集計した結果はこちら👇\n\n"
                    f"{summary_text}\n\n"
                    f"アプリで詳細を確認してね👇\n"
                    f"http://127.0.0.1:5000/"
                )
            )
            mail.send(msg)
            flash("イベントを終了し、参加者に通知メールを送信しました")
        except Exception as e:
            app.logger.error(f"イベント終了通知メール送信エラー: {e}")
            flash("イベントを終了しましたが、メール送信に失敗しました")
    else:
        flash("イベントを終了しました")

    return redirect(url_for("index"))


# ==========================
# 勘定（割り勘）機能
# ==========================

def calculate_billing_amounts(total_amount, participants):
    """参加者ごとの支払額を計算する。"""
    if total_amount < 0:
        raise ValueError("合計金額は0円以上にしてください。")
    if not participants:
        raise ValueError("参加者がいません。")

    count = len(participants)
    base_amount = total_amount // count

    discounted = [p for p in participants if p["discount_enabled"]]
    others = [p for p in participants if not p["discount_enabled"]]

    if discounted and not others:
        raise ValueError("割引対象外の参加者を1人以上設定してください。")

    results = []
    discounted_total = 0

    for p in discounted:
        adjustment = p["adjustment"]
        if adjustment > 0:
            raise ValueError("調整額は0円以下にしてください。")
        final_amount = base_amount + adjustment
        if final_amount < 0:
            raise ValueError("支払額がマイナスになっています。")

        discounted_total += final_amount
        results.append({
            "id": p["id"],
            "username": p["username"],
            "discount_enabled": 1,
            "adjustment": adjustment,
            "base_amount": base_amount,
            "final_amount": final_amount,
        })

    remaining = total_amount - discounted_total

    if others:
        amount, remainder = divmod(remaining, len(others))
        for i, p in enumerate(others):
            results.append({
                "id": p["id"],
                "username": p["username"],
                "discount_enabled": 0,
                "adjustment": 0,
                "base_amount": base_amount,
                "final_amount": amount + (1 if i < remainder else 0),
            })

    if sum(p["final_amount"] for p in results) != total_amount:
        raise ValueError("支払額の合計が総額と一致しません。")

    return results


@app.route("/event/<int:event_id>/billing", methods=["GET", "POST"])
def event_billing(event_id):
    if not login_required():
        return redirect(url_for("login"))

    conn = get_db()

    try:
        event = conn.execute("""
            SELECT events.*, users.username AS host_name
            FROM events
            JOIN users ON users.id = events.host_user_id
            WHERE events.id = ?
        """, (event_id,)).fetchone()

        if event is None:
            return "イベントが見つかりません。", 404

        if session["username"] != event["host_name"]:
            return "主催者のみ利用できます。", 403

        participant_rows = conn.execute("""
            SELECT DISTINCT users.id, users.username
            FROM votes
            JOIN users ON users.id = votes.user_id
            WHERE votes.event_id = ? AND votes.is_join = 1
            ORDER BY users.id
        """, (event_id,)).fetchall()

        participants = [
            {
                "id": p["id"],
                "username": p["username"],
                "discount_enabled": 0,
                "adjustment": -1000,
                "base_amount": 0,
                "final_amount": 0,
            }
            for p in participant_rows
        ]

        billing = conn.execute("""
            SELECT * FROM billings WHERE event_id = ? ORDER BY id DESC LIMIT 1
        """, (event_id,)).fetchone()

        if billing:
            detail_rows = conn.execute("""
                SELECT * FROM billing_details WHERE billing_id = ?
            """, (billing["id"],)).fetchall()

            saved_details = {row["user_id"]: row for row in detail_rows}

            for p in participants:
                saved = saved_details.get(p["id"])
                if saved:
                    p["discount_enabled"] = saved["discount_enabled"]
                    p["adjustment"] = saved["adjustment"]
                    p["base_amount"] = saved["base_amount"]
                    p["final_amount"] = saved["final_amount"]

        total_amount = billing["total_amount"] if billing else 0
        calculated = False
        error = None

        if request.method == "POST":
            action = request.form.get("action", "calculate")

            try:
                total_amount = int(request.form.get("total_amount", "0"))
                if total_amount < 0:
                    raise ValueError("合計金額は0円以上にしてください。")

                for p in participants:
                    p["discount_enabled"] = int(request.form.get(f"discount_enabled_{p['id']}", "0") == "1")
                    adjustment_text = request.form.get(f"adjustment_{p['id']}", "-1000")
                    p["adjustment"] = int(adjustment_text) if p["discount_enabled"] else 0

                participants = calculate_billing_amounts(total_amount, participants)
                calculated = True

                if action == "save":
                    if billing:
                        billing_id = billing["id"]
                        conn.execute("""
                            UPDATE billings SET total_amount = ?, updated_at = datetime('now','localtime') WHERE id = ?
                        """, (total_amount, billing_id))
                    else:
                        cursor = conn.execute("""
                            INSERT INTO billings (event_id, total_amount) VALUES (?, ?)
                        """, (event_id, total_amount))
                        billing_id = cursor.lastrowid

                    for p in participants:
                        existing = conn.execute("""
                            SELECT id FROM billing_details WHERE billing_id = ? AND user_id = ?
                        """, (billing_id, p["id"])).fetchone()

                        values = (p["base_amount"], p["adjustment"], p["final_amount"], p["discount_enabled"])

                        if existing:
                            conn.execute("""
                                UPDATE billing_details SET base_amount = ?, adjustment = ?, final_amount = ?, discount_enabled = ? WHERE id = ?
                            """, (*values, existing["id"]))
                        else:
                            conn.execute("""
                                INSERT INTO billing_details (billing_id, user_id, base_amount, adjustment, final_amount, discount_enabled) VALUES (?, ?, ?, ?, ?, ?)
                            """, (billing_id, p["id"], *values))

                    conn.commit()
                    return redirect(url_for("event_billing", event_id=event_id))

            except ValueError as e:
                error = str(e)

        return render_template(
            "billing.html",
            event=event,
            participants=participants,
            total_amount=total_amount,
            calculated=calculated,
            error=error,
        )

    finally:
        conn.close()


def calculate_standalone_amounts(total_amount, participants):
    """単体勘定の支払額を計算する。"""
    if total_amount < 0:
        raise ValueError("合計金額は0円以上にしてください。")
    if not participants:
        raise ValueError("参加者を1人以上選択してください。")

    count = len(participants)
    base_amount = total_amount // count

    discounted = [p for p in participants if p["discount_enabled"]]
    others = [p for p in participants if not p["discount_enabled"]]

    if discounted and not others:
        raise ValueError("割引対象外の参加者を1人以上選択してください。")

    results = []
    discounted_total = 0

    for p in discounted:
        adjustment = p["adjustment"]
        if adjustment > 0:
            raise ValueError("割引の調整額は0円以下にしてください。")
        final_amount = base_amount + adjustment
        if final_amount < 0:
            raise ValueError("支払額がマイナスになっています。")

        discounted_total += final_amount
        results.append({
            **p,
            "base_amount": base_amount,
            "final_amount": final_amount,
        })

    remaining = total_amount - discounted_total

    if others:
        amount, remainder = divmod(remaining, len(others))
        for i, p in enumerate(others):
            results.append({
                **p,
                "base_amount": base_amount,
                "adjustment": 0,
                "final_amount": amount + (1 if i < remainder else 0),
            })

    if sum(p["final_amount"] for p in results) != total_amount:
        raise ValueError("支払額の合計が総額と一致しません。")

    return results


@app.route("/billing", methods=["GET", "POST"])
def standalone_billing():

    if not login_required():
        return redirect(url_for("login"))

    conn = get_db()

    try:
        current_user = conn.execute("SELECT id FROM users WHERE username = ?", (session["username"],)).fetchone()
        if current_user is None:
            session.clear()
            return redirect(url_for("login"))

        users = conn.execute("SELECT id, username FROM users ORDER BY username").fetchall()

        selected_ids = []
        participants = []
        total_amount = 0
        title = ""
        calculated = False
        error = None

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            action = request.form.get("action", "calculate")

            try:
                total_amount = int(request.form.get("total_amount", "0"))
                if total_amount < 0:
                    raise ValueError("合計金額は0円以上にしてください。")

                selected_ids = list(dict.fromkeys(int(v) for v in request.form.getlist("user_ids")))
                if not selected_ids:
                    raise ValueError("参加者を1人以上選択してください。")

                placeholders = ",".join("?" for _ in selected_ids)
                rows = conn.execute(f"SELECT id, username FROM users WHERE id IN ({placeholders}) ORDER BY username", selected_ids).fetchall()

                participants = []
                for user in rows:
                    user_id = user["id"]
                    discount_enabled = (request.form.get(f"discount_enabled_{user_id}") == "1")
                    adjustment = int(request.form.get(f"adjustment_{user_id}", "-1000"))

                    participants.append({
                        "id": user_id,
                        "username": user["username"],
                        "discount_enabled": int(discount_enabled),
                        "adjustment": adjustment if discount_enabled else 0,
                        "base_amount": 0,
                        "final_amount": 0,
                    })

                participants = calculate_standalone_amounts(total_amount, participants)
                calculated = True

                if action == "save":
                    cursor = conn.execute("""
                        INSERT INTO standalone_billings (title, total_amount, created_by_user_id) VALUES (?, ?, ?)
                    """, (title or "勘定", total_amount, current_user["id"]))
                    billing_id = cursor.lastrowid

                    for p in participants:
                        conn.execute("""
                            INSERT INTO standalone_billing_details (billing_id, user_id, username, base_amount, adjustment, final_amount, discount_enabled) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (billing_id, p["id"], p["username"], p["base_amount"], p["adjustment"], p["final_amount"], p["discount_enabled"]))

                    conn.commit()
                    return redirect(url_for("standalone_billing_detail", billing_id=billing_id))

            except ValueError as e:
                error = str(e)

        history = conn.execute("""
            SELECT b.id, b.title, b.total_amount, b.created_at, u.username AS creator_name
            FROM standalone_billings AS b
            JOIN users AS u ON u.id = b.created_by_user_id
            ORDER BY b.id DESC LIMIT 50
        """).fetchall()

        return render_template(
            "billing_standalone.html",
            users=users,
            participants=participants,
            selected_ids=selected_ids,
            total_amount=total_amount,
            title=title,
            calculated=calculated,
            error=error,
            history=history,
        )

    finally:
        conn.close()


@app.route("/billing/<int:billing_id>")
def standalone_billing_detail(billing_id):

    if not login_required():
        return redirect(url_for("login"))

    conn = get_db()

    try:
        billing = conn.execute("""
            SELECT b.*, u.username AS creator_name
            FROM standalone_billings AS b
            JOIN users AS u ON u.id = b.created_by_user_id
            WHERE b.id = ?
        """, (billing_id,)).fetchone()

        if billing is None:
            return "勘定記録が見つかりません。", 404

        participants = conn.execute("""
            SELECT * FROM standalone_billing_details WHERE billing_id = ? ORDER BY id
        """, (billing_id,)).fetchall()

        return render_template(
            "billing_standalone_detail.html",
            billing=billing,
            participants=participants,
        )

    finally:
        conn.close()


# ==========================
# RESET PASSWORD
# ==========================

@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():

    if request.method == "POST":

        username = request.form["username"]
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        if new_password != confirm_password:

            return render_template(
                "reset_password.html",
                error="パスワードが一致しません"
            )

        password_hash = hashlib.sha256(
            new_password.encode()
        ).hexdigest()

        conn = get_db()

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username=?
            """,
            (username,)
        ).fetchone()

        if user is None:

            conn.close()

            return render_template(
                "reset_password.html",
                error="ユーザーが存在しません"
            )

        conn.execute(
            """
            UPDATE users
            SET password_hash=?
            WHERE username=?
            """,
            (
                password_hash,
                username
            )
        )

        conn.commit()
        conn.close()

        return redirect(
            url_for(
                "login",
                reset=1
            )
        )

    return render_template(
        "reset_password.html"
    )


# ==========================
# LOGOUT
# ==========================

@app.route("/logout")
def logout():

    session.clear()

    flash("ログアウトしました")

    return redirect(url_for("login"))


# ==========================
# MAIN
# ==========================

if __name__ == "__main__":
    app.run(debug=True)