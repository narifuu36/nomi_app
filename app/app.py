from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import hashlib
from collections import Counter
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "secret-key"

DB_NAME = "nomikai.db"


# ==========================
# DB接続
# ==========================

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# ==========================
# ログイン確認
# ==========================

def login_required():
    return "username" in session



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

        username = request.form["username"]
        password = request.form["password"]
        password_confirm = request.form["password_confirm"]

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
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        if exists:

            conn.close()

            return render_template(
                "signup.html",
                error="そのユーザー名は既に使用されています"
            )

        conn.execute(
            """
            INSERT INTO users
            (
                username,
                password_hash
            )
            VALUES
            (
                ?, ?
            )
            """,
            (
                username,
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