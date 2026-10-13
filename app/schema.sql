DROP TABLE IF EXISTS votes;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS users;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
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

    created_at DATETIME NOT NULL DEFAULT (datetime('now','localtime')),

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


CREATE TABLE IF NOT EXISTS billings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL UNIQUE,
    total_amount INTEGER NOT NULL CHECK(total_amount >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (event_id) REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS billing_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    billing_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    base_amount INTEGER NOT NULL CHECK(base_amount >= 0),
    adjustment INTEGER NOT NULL DEFAULT 0,
    final_amount INTEGER NOT NULL CHECK(final_amount >= 0),
    FOREIGN KEY (billing_id) REFERENCES billings(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE (billing_id, user_id)
);
