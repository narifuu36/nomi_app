import sqlite3

DB_NAME = "nomikai.db"

conn = sqlite3.connect(DB_NAME)

with open("schema.sql", "r", encoding="utf-8") as f:
    conn.executescript(f.read())

conn.commit()
conn.close()

print("Database initialized.")