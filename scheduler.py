"""Refreshes the job list once a day from inside the web app.
(On Railway a volume belongs to one service, so a separate cron service couldn't reach the database.)"""
import sqlite3
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import load_jobs
from settings import DATABASE_PATH

JOB_NAME = "load_jobs"
RUN_AFTER_HOUR = 8                       # 08:00 UK time
CHECK_EVERY_SECONDS = 30 * 60            # look at the clock every 30 minutes
UK_TIME = ZoneInfo("Europe/London")


def create_job_runs_table():
    """job_runs = the last date each scheduled job finished successfully."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS job_runs (
            job_name TEXT UNIQUE,
            last_success_date TEXT
        )
    """)
    connection.commit()
    connection.close()


def get_last_success_date():
    """The last date load_jobs finished successfully, or None if it never has."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    row = connection.execute(
        "SELECT last_success_date FROM job_runs WHERE job_name = ?", (JOB_NAME,)).fetchone()
    connection.close()
    if not row:
        return None
    return row[0]


def save_success_date(day):
    """Remember that load_jobs finished successfully on this date."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.execute(
        "INSERT OR REPLACE INTO job_runs (job_name, last_success_date) VALUES (?, ?)", (JOB_NAME, day))
    connection.commit()
    connection.close()


def run_if_due(now=None):
    """Run load_jobs if it's past 08:00 UK time and it hasn't succeeded today. Returns True if it ran OK.
    The date is saved in the database, so restarts and redeploys never cause a second run on the same day."""
    now = now or datetime.now(UK_TIME)
    today = now.date().isoformat()
    if now.hour < RUN_AFTER_HOUR or get_last_success_date() == today:
        return False

    print(f"Scheduled job refresh starting ({today})")
    try:
        load_jobs.run(fetch_from_api=True)
    except Exception as error:
        # Log it and carry on - the date isn't saved, so the next check tries again
        print(f"Scheduled job refresh failed: {error}")
        return False

    save_success_date(today)
    print("Scheduled job refresh finished")
    return True


def keep_checking():
    """Runs forever in the background thread."""
    while True:
        try:
            run_if_due()
        except Exception as error:               # e.g. the database was busy - never let the thread die
            print(f"Scheduler check failed: {error}")
        time.sleep(CHECK_EVERY_SECONDS)


def start_daily_job_refresh():
    """Start the background thread. daemon=True means it stops when the app stops."""
    thread = threading.Thread(target=keep_checking, name="daily-job-refresh", daemon=True)
    thread.start()
