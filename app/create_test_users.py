import sqlite3
import hashlib

DB_NAME = "nomikai.db"

def setup_test_users():
    conn = sqlite3.connect(DB_NAME)
    password_hash = hashlib.sha256("password123".encode()).hexdigest()
    
    # 100人分のテストユーザーをまとめて挿入
    for i in range(1, 101):
        username = f"user_{i}"
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash)
            )
        except sqlite3.IntegrityError:
            # 既に存在している場合はスキップ
            pass
            
    conn.commit()
    conn.close()
    print("テストユーザー（user_1 〜 user_100）の作成が完了しました！")

if __name__ == "__main__":
    setup_test_users()