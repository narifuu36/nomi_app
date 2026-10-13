from flask import Flask, render_template, request, redirect, url_for, session, flash,jsonify
import sqlite3
import requests
import hashlib
from collections import Counter
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "secret-key"

DB_NAME = "nomikai.db"
HOTPEPPER_API_KEY = "50476680ea3687f7"


# ==========================
# DB接続
# ==========================



def calculate_base_amount(total_amount, participant_count):
    """基本料金を10円単位で切り捨てる"""
    if total_amount < 0:
        raise ValueError("合計金額は0円以上で入力してください。")
    if participant_count <= 0:
        raise ValueError("参加者がいません。")

    return (total_amount // participant_count // 10) * 10




def calculate_billing_amounts(total_amount, participants):
    if total_amount < 0:
        raise ValueError("合計金額は0円以上にしてください。")
    if not participants:
        raise ValueError("参加者がいません。")

    count = len(participants)
    base_amount = total_amount // count

    discounted = [
        p for p in participants if p["discount_enabled"]
    ]
    others = [
        p for p in participants if not p["discount_enabled"]
    ]

    if discounted and not others:
        raise ValueError(
            "割引対象者以外の参加者が必要です。"
        )

    results = []

    # 割引対象者の支払額を先に確定
    discounted_total = 0

    for p in discounted:
        adjustment = int(p["adjustment"])

        if adjustment > 0:
            raise ValueError("割引額はマイナスで入力してください。")

        final_amount = base_amount + adjustment

        if final_amount < 0:
            raise ValueError(
                f"{p['name']}さんの支払額が0円未満になります。"
            )

        results.append({
            "id": p["id"],
            "name": p["name"],
            "base_amount": base_amount,
            "adjustment": adjustment,
            "discount_enabled": 1,
            "final_amount": final_amount,
        })

        discounted_total += final_amount

    # 残額を割引対象外の参加者で1円単位まで均等分担
    if others:
        remaining = total_amount - discounted_total

        if remaining < 0:
            raise ValueError(
                "割引対象者の支払額が合計金額を超えています。"
            )

        share, remainder = divmod(remaining, len(others))

        for index, p in enumerate(others):
            results.append({
                "id": p["id"],
                "name": p["name"],
                "base_amount": base_amount,
                "adjustment": int(p["adjustment"]),
                "discount_enabled": 0,
                "final_amount": share + (1 if index < remainder else 0),
            })

    # 元の参加者順に並び替える
    order = {p["id"]: i for i, p in enumerate(participants)}
    results.sort(key=lambda p: order[p["id"]])

    # 合計金額との一致を保証
    if sum(p["final_amount"] for p in results) != total_amount:
        raise ValueError("支払額の合計が一致しません。")

    return results







@app.route("/event/<int:event_id>/billing", methods=["GET", "POST"])
def event_billing(event_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    conn = get_db()
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        event = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()

        if event is None:
            flash("イベントが見つかりません。")
            return redirect(url_for("index"))

        if event["host_user_id"] != user_id:
            flash("勘定を編集できるのは主催者のみです。")
            return redirect(url_for("index"))

        participants = conn.execute("""
            SELECT DISTINCT u.id, u.username AS name
            FROM votes v
            JOIN users u ON u.id = v.user_id
            WHERE v.event_id = ? AND v.is_join = 1
            ORDER BY u.id
        """, (event_id,)).fetchall()

        billing = conn.execute(
            "SELECT * FROM billings WHERE event_id = ?", (event_id,)
        ).fetchone()

        details = {}
        if billing:
            rows = conn.execute("""
                SELECT user_id, base_amount, adjustment,
                       final_amount, discount_enabled
                FROM billing_details
                WHERE billing_id = ?
            """, (billing["id"],)).fetchall()
            details = {row["user_id"]: dict(row) for row in rows}

        total_amount = billing["total_amount"] if billing else 0
        calculated = False
        error = None

        if request.method == "POST":
            action = request.form.get("action", "calculate")

            try:
                total_amount = int(request.form.get("total_amount", ""))

                if total_amount < 0:
                    raise ValueError("合計金額は0円以上にしてください。")

                if not participants:
                    raise ValueError("参加すると回答したユーザーがいません。")

                # フォームの割引設定を参加者ごとに取得
                input_participants = []

                for p in participants:
                    uid = p["id"]
                    old = details.get(uid, {})

                    enabled = (
                        request.form.get(f"discount_enabled_{uid}") == "on"
                    )

                    raw_adjustment = request.form.get(
                        f"adjustment_{uid}",
                        str(old.get("adjustment", -1000))
                    )
                    adjustment = int(raw_adjustment)

                    input_participants.append({
                        "id": uid,
                        "name": p["name"],
                        "discount_enabled": enabled,
                        "adjustment": adjustment,
                    })

                # 割引分を割引対象外の参加者で分担
                display_participants = calculate_billing_amounts(
                    total_amount, input_participants
                )

                details = {
                    p["id"]: p for p in display_participants
                }
                calculated = True

                if action == "save":
                    conn.execute("BEGIN")

                    conn.execute("""
                        INSERT INTO billings (event_id, total_amount)
                        VALUES (?, ?)
                        ON CONFLICT(event_id) DO UPDATE SET
                            total_amount = excluded.total_amount,
                            updated_at = datetime('now', 'localtime')
                    """, (event_id, total_amount))

                    billing_id = conn.execute(
                        "SELECT id FROM billings WHERE event_id = ?",
                        (event_id,)
                    ).fetchone()["id"]

                    participant_ids = [p["id"] for p in participants]
                    placeholders = ",".join("?" for _ in participant_ids)

                    conn.execute(
                        f"""DELETE FROM billing_details
                            WHERE billing_id = ?
                            AND user_id NOT IN ({placeholders})""",
                        [billing_id, *participant_ids]
                    )

                    for p in display_participants:
                        conn.execute("""
                            INSERT INTO billing_details (
                                billing_id, user_id, base_amount,
                                adjustment, final_amount, discount_enabled
                            )
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(billing_id, user_id) DO UPDATE SET
                                base_amount = excluded.base_amount,
                                adjustment = excluded.adjustment,
                                final_amount = excluded.final_amount,
                                discount_enabled = excluded.discount_enabled
                        """, (
                            billing_id,
                            p["id"],
                            p["base_amount"],
                            p["adjustment"],
                            p["final_amount"],
                            p["discount_enabled"],
                        ))

                    conn.commit()
                    flash("勘定を保存しました。")
                    return redirect(url_for(
                        "event_billing", event_id=event_id
                    ))

            except (ValueError, TypeError) as e:
                conn.rollback()
                error = str(e) or "金額を正しく入力してください。"

            except Exception:
                conn.rollback()
                app.logger.exception("勘定処理に失敗しました")
                error = "勘定処理に失敗しました。"

        # 初期表示・エラー時の表示データ
        if calculated:
            shown_participants = display_participants
        else:
            base_amount = (
                calculate_base_amount(total_amount, len(participants))
                if participants and total_amount >= 0 else 0
            )

            shown_participants = []

            for p in participants:
                d = details.get(p["id"], {})
                enabled = d.get("discount_enabled", 0)
                adjustment = d.get("adjustment", -1000)

                shown_participants.append({
                    "id": p["id"],
                    "name": p["name"],
                    "base_amount": d.get("base_amount", base_amount),
                    "adjustment": adjustment,
                    "discount_enabled": enabled,
                    "final_amount": d.get("final_amount", base_amount),
                })

        paid_total = sum(
            p["final_amount"] for p in shown_participants
        )
        difference = total_amount - paid_total

        return render_template(
            "billing.html",
            event=event,
            participants=shown_participants,
            total_amount=total_amount,
            paid_total=paid_total,
            difference=difference,
            billing=billing,
            calculated=calculated,
            error=error,
        )

    finally:
        conn.close()





def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# ==========================
# ログイン確認
# ==========================

def login_required():
    return "user_id" in session



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

        end_time = created + timedelta(hours=24)

        if datetime.now() >= end_time:

            conn.execute("""
                UPDATE events
                SET
                    is_active = 0,
                    finished_at = CURRENT_TIMESTAMP
                WHERE id=?
            """, (event["id"],))

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
    event=event,
    is_host=(
        event is not None
        and event["host_user_id"] == session.get("user_id")
    )
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

            session["user_id"] = user["id"]
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

    # 同時作成防止
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
        conn.close()

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

    # 残り時間計算
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

        # 重複投票防止
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



@app.route("/hotpepper/search")
def hotpepper_search():
    keyword = request.args.get("keyword", "").strip()
    genre = request.args.get("genre", "").strip()
    budget = request.args.get("budget", "").strip()
    private_room = request.args.get("private_room", "0")
    free_drink = request.args.get("free_drink", "0")

    if not keyword:
        return jsonify({"shops": []})

    # APIが受け付ける検索条件
    params = {
        "key": HOTPEPPER_API_KEY,
        "keyword": keyword,
        "format": "json",
        "count": 30,
        "private_room": "1" if private_room == "1" else "0",
        "free_drink": "1" if free_drink == "1" else "0"
    }

    # 指定がある条件だけ追加
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
                # 既存の店舗一覧用
                "name": shop.get("name", ""),
                "address": shop.get("address", ""),
                "genre": shop.get("genre", {}).get("name", ""),
                "budget": shop.get("budget", {}).get("name", ""),
                "station": shop.get("station_name", ""),
                "url": shop.get("urls", {}).get("pc", ""),

                # 店舗詳細用
                "phone": shop.get("tel", ""),
                "open": shop.get("open", ""),
                "close": shop.get("close", ""),
                "access": shop.get("access", ""),
                "catch": shop.get("catch", ""),
                "capacity": shop.get("capacity", ""),
                "parking": shop.get("parking", ""),
                "private_room": shop.get("private_room", ""),
                "free_drink": shop.get("free_drink", ""),

                # 地図用
                "lat": shop.get("lat", ""),
                "lng": shop.get("lng", "")
            })

        return jsonify({"shops": results})

    except requests.exceptions.Timeout:
        app.logger.warning("HotPepper API timeout")
        return jsonify({
            "error": "店舗検索がタイムアウトしました"
        }), 504

    except requests.exceptions.RequestException:
        app.logger.exception("HotPepper API request failed")
        return jsonify({
            "error": "店舗情報の取得に失敗しました"
        }), 502

    except ValueError:
        app.logger.exception("HotPepper API JSON parsing failed")
        return jsonify({
            "error": "店舗情報を正しく読み込めませんでした"
        }), 502


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

    # ログインユーザーが主催者か判定
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
# COMPLETE
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

    flash("イベントを作成しました")

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