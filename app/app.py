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
# イベント取得 or 作成
# ------------------------
def get_active_event():
    conn = get_db()
    event = conn.execute(
        "SELECT * FROM events WHERE is_active=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()

    # 24時間チェック
    if event:
        created = datetime.strptime(event["created_at"], "%Y-%m-%d %H:%M:%S")
        if datetime.now() - created > timedelta(hours=24):
            reset_event()
            return None

    return event


def create_event(user_id):
    conn = get_db()
    conn.execute(
        "INSERT INTO events (host_user_id) VALUES (?)",
        (user_id,)
    )
    conn.commit()


def reset_event():
    conn = get_db()
    conn.execute("UPDATE events SET is_active=0 WHERE is_active=1")
    conn.execute("DELETE FROM responses")
    conn.commit()


# ------------------------
# 仮ログイン（ユーザー固定）
# ------------------------
@app.route("/login/<int:user_id>")
def login(user_id):
    session["user_id"] = user_id
    return redirect(url_for("index"))


# ------------------------
# 画面A
# ------------------------
@app.route("/")
def index():
    user_id = session.get("user_id", 1)  # 仮固定

    event = get_active_event()

    if event:
        return redirect(url_for("page_b"))

    return render_template("a.html")


# ------------------------
# 「飲みたい！」押下
# ------------------------
@app.route("/start", methods=["POST"])
def start():
    user_id = session.get("user_id", 1)

    if not get_active_event():
        create_event(user_id)

    return redirect(url_for("page_b"))


# ------------------------
# 画面B
# ------------------------
@app.route("/b", methods=["GET", "POST"])
def page_b():
    user_id = session.get("user_id", 1)
    conn = get_db()

    event = get_active_event()
    if not event:
        return redirect(url_for("index"))

    is_host = (event["host_user_id"] == user_id)

    if request.method == "POST":
        will_join = int(request.form.get("will_join", 0))

        place = request.form.get("place")
        date = request.form.get("date")
        time_slot = request.form.get("time_slot")

        conn.execute("""
            INSERT INTO responses (user_id, event_id, will_join, place, date, time_slot)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, event["id"], will_join, place, date, time_slot))

        conn.commit()

        return redirect(url_for("page_c"))

    users = conn.execute("SELECT * FROM users").fetchall()

    return render_template("b.html", is_host=is_host, users=users)


# ------------------------
# 完了ボタン（主催者）
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
        return redirect(url_for("index"))

    responses = conn.execute("""
        SELECT r.*, u.name FROM responses r
        JOIN users u ON r.user_id = u.id
        WHERE r.event_id = ?
    """, (event["id"],)).fetchall()

    # 集計
    places = {}
    dates = {}
    times = {}
    participants = []

    for r in responses:
        if r["will_join"]:
            participants.append(r["name"])

            places[r["place"]] = places.get(r["place"], 0) + 1
            dates[r["date"]] = dates.get(r["date"], 0) + 1
            times[r["time_slot"]] = times.get(r["time_slot"], 0) + 1

    return render_template(
        "c.html",
        participants=participants,
        places=places,
        dates=dates,
        times=times
    )


# ------------------------
# 起動
# ------------------------
if __name__ == "__main__":
    app.run(debug=True)