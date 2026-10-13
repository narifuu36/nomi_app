import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_NAME = str(BASE_DIR / "nomikai.db")
SCHEMA_PATH = BASE_DIR / "schema.sql"

conn = sqlite3.connect(DB_NAME)

with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
    conn.executescript(f.read())

conn.commit()
conn.close()

print("Database initialized.")