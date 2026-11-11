import sqlite3 # Python's built-in module for SQLite databases
from fastapi import FastAPI, Request # Importing FastAPI the web framework
from fastapi.templating import Jinja2Templates # Importing the Jinja2 templates we are going to use with HTML
from datetime import date, timedelta # So we can filter for dates
from fastapi.staticfiles import StaticFiles # Importing the CSS file

from summaries import get_summary, create_summaries_table

create_summaries_table()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Gets jobs from the database, newest first, optionally filtered by city and date posted
def get_jobs(city=None, days=None):
    sql = "SELECT title, company_name, company_website, place, date_posted, link FROM jobs"
    conditions = []
    values = []

    if city:
        conditions.append("place = ?")
        values.append(city)

    if days is not None:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        conditions.append("date_posted >= ?")
        values.append(cutoff)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY date_posted DESC"

    connection = sqlite3.connect("landly.db")
    connection.row_factory = sqlite3.Row
    rows = connection.execute(sql, values).fetchall()
    connection.close()
    return [dict(row) for row in rows]

# When someone visits /jobs (optionally with ?city=...&days=...): get matching jobs and fill jobs.html, if days has something in it, turn it into a number. Otherwise, use None
@app.get("/jobs")
def show_jobs(request: Request, city: str = None, days: str = None):
    days_number = int(days) if days else None
    jobs = get_jobs(city, days_number)
    return templates.TemplateResponse(request, "jobs.html", {"jobs": jobs, "city": city, "days": days_number})

@app.get("/summary")
def show_summary(company: str):
    connection = sqlite3.connect("landly.db")
    connection.row_factory = sqlite3.Row
    sql = "SELECT company_name, company_website, description FROM jobs WHERE company_name = ? LIMIT 1"
    row = connection.execute(sql, (company,)).fetchone()
    connection.close()

    summary = get_summary(row["company_name"], row["company_website"], row["description"])
    return {"summary": summary}

