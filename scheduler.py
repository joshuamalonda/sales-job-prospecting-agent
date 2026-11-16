"""Refreshes the job list once a day from inside the web app.
(On Railway a volume belongs to one service, so a separate cron service couldn't reach the database.)"""
import sqlite3
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import load_jobs
from settings import BACKFILL_DAYS, DATABASE_PATH

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


def get_last_success_date(job_name=JOB_NAME):
    """The last date this job finished successfully, or None if it never has."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    row = connection.execute(
        "SELECT last_success_date FROM job_runs WHERE job_name = ?", (job_name,)).fetchone()
    connection.close()
    if not row:
        return None
    return row[0]


def save_success_date(day, job_name=JOB_NAME):
    """Remember that this job finished successfully on this date."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.execute(
        "INSERT OR REPLACE INTO job_runs (job_name, last_success_date) VALUES (?, ?)", (job_name, day))
    connection.commit()
    connection.close()


def backfill_job_name(days):
    """e.g. "backfill_30" - one name per BACKFILL_DAYS value, so each value runs once."""
    return f"backfill_{days}"


def backfill_is_pending(days=None):
    """True if BACKFILL_DAYS is set and that backfill hasn't succeeded yet."""
    days = BACKFILL_DAYS if days is None else days
    return days > 0 and get_last_success_date(backfill_job_name(days)) is None


def run_backfill(today, days=None):
    """The one-off backfill: fetch the last N days. Runs at the first check after startup, whatever the time.
    On success it's recorded (so it never repeats) and also counts as today's normal load."""
    days = BACKFILL_DAYS if days is None else days
    print(f"Backfill starting: fetching postings from the last {days} days")
    try:
        load_jobs.run(fetch_from_api=True, days_back=days)
    except Exception as error:
        # Not recorded, so the next check (30 minutes later) tries the backfill again
        print(f"Backfill failed: {error}")
        return False
    save_success_date(today, backfill_job_name(days))
    save_success_date(today)
    print("Backfill finished - daily loads are back to the normal window")
    return True


def run_if_due(now=None):
    """Run the backfill if one is pending; otherwise run load_jobs if it's past 08:00 UK time and it
    hasn't succeeded today. Returns True if something ran OK.
    The date is saved in the database, so restarts and redeploys never cause a second run on the same day."""
    now = now or datetime.now(UK_TIME)
    today = now.date().isoformat()
    if backfill_is_pending():
        return run_backfill(today)
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
