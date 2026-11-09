import sqlite3
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Gets all jobs from the database, newest first
def get_jobs():
    connection = sqlite3.connect("landly.db")
    connection.row_factory = sqlite3.Row
    rows = connection.execute("""
        SELECT title, company_name, place, date_posted, link
        FROM jobs
        ORDER BY date_posted DESC
    """).fetchall()
    connection.close()
    return [dict(row) for row in rows]


@app.get("/jobs")
def show_jobs(request: Request):
    jobs = get_jobs()
    return templates.TemplateResponse(request, "jobs.html", {"jobs": jobs})