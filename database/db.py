import sqlite3
from datetime import date

from werkzeug.security import generate_password_hash

DB_PATH = "expense_tracker.db"

CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

CREATE_EXPENSES_TABLE = """
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    category TEXT NOT NULL,
    date TEXT NOT NULL,
    description TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users (id)
);
"""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    try:
        conn.execute(CREATE_USERS_TABLE)
        conn.execute(CREATE_EXPENSES_TABLE)
        conn.commit()
    finally:
        conn.close()


# NOTE: This step only implements standalone get_db()/init_db()/seed_db().
# Request-scoped connection management (Flask's `g` object + teardown_appcontext)
# will be wired up in a later step once routes start reading/writing the DB.
def seed_db():
    conn = get_db()
    try:
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None:
            return

        password_hash = generate_password_hash("demo123")
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Demo User", "demo@spendly.com", password_hash),
        )
        user_id = cursor.lastrowid

        today = date.today()
        expenses = [
            (user_id, 45.50, "Food", today.replace(day=2).isoformat(), "Groceries at Whole Foods"),
            (user_id, 18.00, "Transport", today.replace(day=3).isoformat(), "Uber ride to work"),
            (user_id, 120.00, "Bills", today.replace(day=5).isoformat(), "Electricity bill"),
            (user_id, 60.00, "Health", today.replace(day=8).isoformat(), "Pharmacy — prescription refill"),
            (user_id, 32.99, "Entertainment", today.replace(day=10).isoformat(), "Movie tickets"),
            (user_id, 85.25, "Shopping", today.replace(day=14).isoformat(), "New running shoes"),
            (user_id, 15.00, "Other", today.replace(day=18).isoformat(), "Miscellaneous — gift wrap"),
            (user_id, 27.75, "Food", today.replace(day=22).isoformat(), "Dinner at a local restaurant"),
        ]
        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            expenses,
        )
        conn.commit()
    finally:
        conn.close()
