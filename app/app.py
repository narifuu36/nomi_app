from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_mail import Mail, Message
import sqlite3
import requests
import hashlib
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

app = Flask(__name__)
app.secret_key = "secret-key"

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
# DB接続＆初期化
# ==========================

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db_columns():
    """リマインド管理用のカラムが無ければ自動追加する"""
    conn = get_db()
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


init_db_columns()


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

    # 一番票数が多かったものを取得
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
                        recipients=emails,
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

            # 集計結果テキストと対象メールアドレスを取得
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
                        recipients=emails,
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
                        recipients=emails,
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
                    recipients=emails,
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

    # ★ 投票結果の集計テキストと参加者のメールアドレスを取得
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

    # ★ メール通知（結果入りの本文）
    if emails:
        try:
            msg = Message(
                subject=f"【決定】飲み会「{event['title']}」の日程・詳細が決まったよ！",
                recipients=emails,
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