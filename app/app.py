from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "secret-key"

DB = "nomikai.db"


# ------------------------
# DB接続
# ------------------------
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


# ------------------------
# ログイン
# ------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("name")

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE name=?",
            (name,)
        ).fetchone()

        if not user:
            conn.execute(
                "INSERT INTO users (name) VALUES (?)",
                (name,)
            )
            conn.commit()

            user = conn.execute(
                "SELECT * FROM users WHERE name=?",
                (name,)
            ).fetchone()

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]

        conn.close()
        return redirect(url_for("index"))

    return render_template("login.html")


# ------------------------
# イベント取得
# ------------------------
def get_active_event():
    conn = get_db()
    event = conn.execute(
        "SELECT * FROM events WHERE is_active=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if event:
        created = datetime.strptime(event["created_at"], "%Y-%m-%d %H:%M:%S")
        if datetime.now() - created > timedelta(hours=24):
            reset_event()
            conn.close()
            return None

    conn.close()
    return event


def create_event(user_id):
    conn = get_db()
    conn.execute(
        "INSERT INTO events (host_user_id) VALUES (?)",
        (user_id,)
    )
    conn.commit()
    conn.close()


def reset_event():
    conn = get_db()
    conn.execute("UPDATE events SET is_active=0 WHERE is_active=1")
    conn.execute("DELETE FROM responses")
    conn.commit()
    conn.close()


# ------------------------
# 画面A
# ------------------------
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))

    event = get_active_event()

    if event:
        return redirect(url_for("page_b"))

    return render_template("a.html")


# ------------------------
# 「飲みたい！」
# ------------------------
@app.route("/start", methods=["POST"])
def start():
    user_id = session.get("user_id")

    if not get_active_event():
        create_event(user_id)

    return redirect(url_for("page_b"))


# ------------------------
# 画面B
# ------------------------
@app.route("/b", methods=["GET", "POST"])
def page_b():
    user_id = session.get("user_id")
    conn = get_db()

    event = get_active_event()
    if not event:
        conn.close()
        return redirect(url_for("index"))

    is_host = (event["host_user_id"] == user_id)

    # ------------------------
    # POST（投票）
    # ------------------------
    if request.method == "POST":
        will_join = int(request.form.get("will_join", 0))

        place = request.form.get("place")
        place_free = request.form.get("place_free")

        if place_free:
            place = place_free

        # 🔥 複数日程
        selected_dates = request.form.getlist("dates")
        date_str = ",".join(selected_dates)

        time_slot = request.form.get("time_slot")

        # 🔥 重複防止
        conn.execute("""
            DELETE FROM responses
            WHERE user_id=? AND event_id=?
        """, (user_id, event["id"]))

        conn.execute("""
            INSERT INTO responses (user_id, event_id, will_join, place, date, time_slot)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, event["id"], will_join, place, date_str, time_slot))

        conn.commit()
        conn.close()

        return redirect(url_for("page_c"))

    # ------------------------
    # GET（画面表示）
    # ------------------------
    users = conn.execute("SELECT * FROM users").fetchall()
    conn.close()

    # 🔥 日程ボタン用（今日から7日）
    today = datetime.now()
    date_list = [
        (today + timedelta(days=i)).strftime("%m/%d(%a)")
        for i in range(7)
    ]

    return render_template(
        "b.html",
        is_host=is_host,
        users=users,
        date_list=date_list
    )


# ------------------------
# 完了
# ------------------------
@app.route("/finish", methods=["POST"])
def finish():
    reset_event()
    return redirect(url_for("index"))


# ------------------------
# 画面C（集計）
# ------------------------
@app.route("/c")
def page_c():
    conn = get_db()

    event = get_active_event()
    if not event:
        conn.close()
        return redirect(url_for("index"))

    is_host = (event["host_user_id"] == session.get("user_id"))

    responses = conn.execute("""
        SELECT r.*, u.name FROM responses r
        JOIN users u ON r.user_id = u.id
        WHERE r.event_id = ?
    """, (event["id"],)).fetchall()

    places = {}
    dates = {}
    times = {}
    participants = []

    for r in responses:
        if r["will_join"] == 1:
            participants.append(r["name"])

            if r["place"]:
                places[r["place"]] = places.get(r["place"], 0) + 1

            # 🔥 複数日程を分解
            if r["date"]:
                for d in r["date"].split(","):
                    dates[d] = dates.get(d, 0) + 1

            if r["time_slot"]:
                times[r["time_slot"]] = times.get(r["time_slot"], 0) + 1

    conn.close()

    return render_template(
        "c.html",
        participants=list(set(participants)),
        places=places,
        dates=dates,
        times=times,
        is_host=is_host
    )


# ------------------------
# 起動
# ------------------------
if __name__ == "__main__":
    app.run(debug=True)