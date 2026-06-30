from locust import HttpUser, task, between
import random

class NomikaiVoteUser(HttpUser):
    # 各ユーザーの操作間隔を0.5秒〜1.5秒に設定（高負荷にするため短め）
    wait_time = between(0.5, 1.5)

    def on_start(self):
        """擬似ユーザーが立ち上がった時に1回だけ実行されるログイン処理"""
        # 1〜100のランダムなユーザーでログイン
        user_number = random.randint(1, 100)
        self.username = f"user_{user_number}"
        
        payload = {
            "username": self.username,
            "password": "password123"
        }
        # ログインを実行してセッションを維持
        self.client.post("/login", data=payload)

    @task
    def vote_task(self):
        """同時に大量実行したい投票処理（/event の POST）"""
        vote_data = {
            "will_join": "1",                    # 1: 参加、0: 不参加
            "place": ["伏見"],                   # 選択肢（配列）
            "date": ["7/1"],             # 選択肢（配列）
            "time_slot": ["19:00-21:00"]               # 選択肢（配列）
        }
        
        # 投票リクエストを送信
        with self.client.post("/event", data=vote_data, catch_response=True) as response:
            if "database is locked" in response.text:
                response.failure("SQLite Database Locked!")
            elif response.status_code == 500:
                response.failure("Internal Server Error (Check Flask Console)")