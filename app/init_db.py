import sqlite3

conn = sqlite3.connect('nomikai.db')
with open('schema.sql', 'r', encoding='utf-8') as f:
    conn.executescript(f.read())

# 仮ユーザー投入
users = [
    ('tanaka', 'pass1234'),
    ('sato', 'pass1234'),
    ('suzuki', 'pass1234'),
    ('takahashi', 'pass1234')
]

for username, password in users:
    conn.execute(
        "INSERT INTO users (username, password) VALUES (?, ?)",
        (username, password)
    )

conn.commit()
conn.close()

print('DB initialized.')