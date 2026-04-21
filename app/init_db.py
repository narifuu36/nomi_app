import sqlite3

conn = sqlite3.connect('nomikai.db')
with open('schema.sql', 'r', encoding='utf-8') as f:
    conn.executescript(f.read())

# 仮ユーザー投入
users = ["田中", "佐藤", "鈴木", "高橋"]

for name in users:
    conn.execute("INSERT INTO users (name) VALUES (?)", (name,))

conn.commit()
conn.close()

print("DB initialized.")