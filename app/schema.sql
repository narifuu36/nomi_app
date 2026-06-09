DROP TABLE IF EXISTS votes;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS events;

CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    title TEXT NOT NULL,

    host_user_id INTEGER NOT NULL,

    places TEXT,
    dates TEXT,
    times TEXT,

    is_active BOOLEAN NOT NULL DEFAULT 1,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    finished_at DATETIME,

    FOREIGN KEY(host_user_id)
        REFERENCES users(id)
);
CREATE TABLE votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    event_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,

    is_join INTEGER NOT NULL,

    place TEXT,
    date TEXT,
    time_slot TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(event_id)
        REFERENCES events(id),

    FOREIGN KEY(user_id)
        REFERENCES users(id)
);