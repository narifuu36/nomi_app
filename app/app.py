from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from collections import Counter

app = Flask(__name__)
app.secret_key = "secret-key"

DB_NAME = "nomikai.db"


# DB接続
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# トップ画面
@app.route("/")
def index():
    return render_template(
        "index.html",
        username=session.get("username")
    )


# ログイン
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]

        session["username"] = username

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE name = ?",
            (username,)
        ).fetchone()

        if not user:
            conn.execute(
                "INSERT INTO users (name) VALUES (?)",
                (username,)
            )
            conn.commit()

        conn.close()

        return redirect(url_for("index"))

    return render_template("login.html")


# 新規登録
@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        username = request.form["username"]

        conn = get_db()

        exists = conn.execute(
            "SELECT * FROM users WHERE name = ?",
            (username,)
        ).fetchone()

        if exists:
            return render_template(
                "signup.html",
                error="そのユーザー名は既に使用されています"
            )

        conn.execute(
            "INSERT INTO users (name) VALUES (?)",
            (username,)
        )

        conn.commit()
        conn.close()

        session["username"] = username

        return redirect(url_for("index"))

    return render_template("signup.html")


# イベント画面
@app.route("/event", methods=["GET", "POST"])
def event():

    conn = get_db()

    event = conn.execute(
        "SELECT * FROM events WHERE is_active = 1 LIMIT 1"
    ).fetchone()

    # イベントがない場合は自動作成
    if not event:

        username = session.get("username")

        if not username:
            return redirect(url_for("login"))

        user = conn.execute(
            "SELECT * FROM users WHERE name = ?",
            (username,)
        ).fetchone()

        # ユーザーが存在しない場合のみ作成
        if user is None:
            conn.execute(
                "INSERT INTO users (name) VALUES (?)",
                (username,)
            )
            conn.commit()

            user = conn.execute(
                "SELECT * FROM users WHERE name = ?",
                (username,)
            ).fetchone()

        conn.execute(
            """
            INSERT INTO events (host_user_id)
            VALUES (?)
            """,
            (user["id"],)
        )

        conn.commit()

        event = conn.execute(
            "SELECT * FROM events WHERE is_active = 1 LIMIT 1"
        ).fetchone()

    # 投票送信
    if request.method == "POST":

        username = session.get("username")

        if not username:
            return redirect(url_for("login"))

        user = conn.execute(
            "SELECT * FROM users WHERE name = ?",
            (username,)
        ).fetchone()

        will_join = int(request.form["will_join"])
        place = request.form.get("place")
        date = ",".join(request.form.getlist("date"))
        time_slot = request.form.get("time_slot")

        conn.execute(
            """
            INSERT INTO responses
            (
                user_id,
                event_id,
                will_join,
                place,
                date,
                time_slot
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                event["id"],
                will_join,
                place,
                date,
                time_slot
            )
        )

        conn.commit()

        return redirect(url_for("result"))

    conn.close()

    return render_template(
        "event.html",
        username=session.get("username", "ゲスト")
    )


# 集計画面
@app.route("/result")
def result():

    conn = get_db()

    event = conn.execute(
        "SELECT * FROM events WHERE is_active = 1 LIMIT 1"
    ).fetchone()

    responses = conn.execute(
        """
        SELECT responses.*, users.name
        FROM responses
        JOIN users
        ON responses.user_id = users.id
        WHERE event_id = ?
        """,
        (event["id"],)
    ).fetchall()

    place_counter = Counter()
    date_counter = Counter()
    time_counter = Counter()

    participants = []

    for r in responses:

        if r["will_join"] == 1:
            participants.append(r["name"])

        if r["place"]:
            place_counter[r["place"]] += 1

        if r["date"]:

            dates = r["date"].split(",")

            for d in dates:
                date_counter[d] += 1

        if r["time_slot"]:
            time_counter[r["time_slot"]] += 1

    conn.close()

    return render_template(
        "result.html",
        username=session.get("username", "ゲスト"),
        participants=participants,
        place_results=place_counter.items(),
        date_results=date_counter.items(),
        time_results=time_counter.items()
    )


# イベント終了
@app.route("/complete")
def complete():

    conn = get_db()

    conn.execute(
        "UPDATE events SET is_active = 0 WHERE is_active = 1"
    )

    conn.commit()
    conn.close()

    return redirect(url_for("index"))


# ログアウト
@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)