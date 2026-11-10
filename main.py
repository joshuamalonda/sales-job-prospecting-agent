import sqlite3 # Python's built-in module for SQLite databases
from fastapi import FastAPI, Request # Importing FastAPI the web framework
from fastapi.templating import Jinja2Templates # Importing the Jinja2 templates we are going to use with HTML

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

# When someone visits /jobs: get the jobs from the database and fill them into jobs.html
@app.get("/jobs")
def show_jobs(request: Request):
    jobs = get_jobs()
    return templates.TemplateResponse(request, "jobs.html", {"jobs": jobs})