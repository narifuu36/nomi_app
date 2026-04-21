DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS responses;

-- ユーザー（仮固定）
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);

-- イベント（1つだけ運用の想定）
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1,
    host_user_id INTEGER
);

-- 回答データ
CREATE TABLE responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    event_id INTEGER,
    will_join INTEGER,
    place TEXT,
    date TEXT,
    time_slot TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);