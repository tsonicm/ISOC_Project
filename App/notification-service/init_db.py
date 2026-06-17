"""
Database initialization for Notification Service.
Creates table: notifications in notifications.db
"""

import sqlite3
import os


DB_PATH = os.environ.get("DB_PATH", "/data/notifications.db")


def get_db():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they do not exist."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_type TEXT NOT NULL CHECK(recipient_type IN ('patient', 'doctor')),
            recipient_id INTEGER NOT NULL,
            appointment_id INTEGER,
            channel TEXT NOT NULL DEFAULT 'log' CHECK(channel IN ('email', 'log')),
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'sent', 'failed', 'read')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            sent_at TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
