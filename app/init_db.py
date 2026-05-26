import sqlite3

conn = sqlite3.connect('nomikai.db')

with open('schema.sql', 'r', encoding='utf-8') as f:
    conn.executescript(f.read())

# 仮ユーザー
users = [
    ("田中", "pass"),
    ("佐藤", "pass"),
    ("鈴木", "pass"),
    ("高橋", "pass")
]

for user in users:
    conn.execute(
        "INSERT INTO users (name, password) VALUES (?, ?)",
        user
    )

# 仮イベント
conn.execute("""
INSERT INTO events (title, created_by)
VALUES (?, ?)
""", ("飲み会テスト", 1))

conn.commit()
conn.close()

print("DB initialized.")