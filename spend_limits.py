"""Daily caps on paid API work, so a busy day (or a bug) can't run up a big bill."""
import sqlite3
from datetime import date

from settings import DATABASE_PATH


def create_usage_table():
    """paid_usage = one row each time a paid plan build or contact lookup is started."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS paid_usage (
            used_on TEXT,
            kind TEXT,
            company_name TEXT
        )
    """)
    connection.commit()
    connection.close()


def use_daily_allowance(kind, company_name, limit):
    """Record one use of today's allowance and return True - or return False if today's limit is reached.
    kind is "plan" or "contacts". Call this BEFORE any paid API call (it never makes one itself)."""
    today = date.today().isoformat()
    connection = sqlite3.connect(DATABASE_PATH, timeout=30, isolation_level=None)
    try:
        # BEGIN IMMEDIATE locks the database for writing straight away, so two clicks at the
        # same moment can't both see "9 used" and both go ahead
        connection.execute("BEGIN IMMEDIATE")
        used_today = connection.execute(
            "SELECT COUNT(*) FROM paid_usage WHERE used_on = ? AND kind = ?", (today, kind)).fetchone()[0]
        if used_today >= limit:
            connection.execute("ROLLBACK")
            return False
        connection.execute(
            "INSERT INTO paid_usage (used_on, kind, company_name) VALUES (?, ?, ?)", (today, kind, company_name))
        connection.execute("COMMIT")
        return True
    finally:
        connection.close()
