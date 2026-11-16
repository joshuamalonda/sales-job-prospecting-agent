import os
import secrets                                   # compare passwords safely (see require_login)
import sqlite3                                   # Python's built-in SQLite database module
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles      # serves the files in the static/ folder (CSS)
from fastapi.templating import Jinja2Templates   # fills the HTML templates with data

from contacts import create_contacts_tables, get_decision_makers, has_contact_lookup
from load_jobs import create_database as create_jobs_table
from prospecting import (create_packs_table, get_edited_html, get_pack, has_saved_pack, save_edited_html,
                         territory_for)
from scheduler import create_job_runs_table, start_daily_job_refresh
from settings import (APP_PASSWORD, APP_USERNAME, DATABASE_PATH, ENABLE_SCHEDULER,
                      MAX_CONTACT_LOOKUPS_PER_DAY, MAX_PLANS_PER_DAY)
from spend_limits import create_usage_table, use_daily_allowance
from summaries import create_summaries_table, get_summary

MAX_EDIT_SIZE = 500_000          # characters - a saved plan edit bigger than this is rejected

# Never run without a password: stop right here with a clear message instead
if not APP_USERNAME or not APP_PASSWORD:
    raise RuntimeError("APP_USERNAME and APP_PASSWORD must both be set (in .env locally, "
                       "or in Railway's Variables tab). Landly won't start without a login.")


def create_applied_table():
    """Companies I've applied to (one row per company, so every job at that company shows as applied)."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS applied_companies (
            company_name TEXT UNIQUE,
            applied_at TEXT
        )
    """)
    connection.commit()
    connection.close()


# Make sure every table exists before the app starts (a brand-new database on Railway starts empty)
create_jobs_table()
create_packs_table()
create_contacts_tables()
create_summaries_table()
create_applied_table()
create_usage_table()
create_job_runs_table()


@asynccontextmanager
async def lifespan(app):
    """Runs once when the app starts. The daily job refresh is only switched on where ENABLE_SCHEDULER=true
    (Railway), so it never runs on my laptop (e.g. every time uvicorn --reload restarts)."""
    if ENABLE_SCHEDULER:
        start_daily_job_refresh()
    yield


basic_auth = HTTPBasic()          # makes the browser show its built-in username/password box


def require_login(credentials: HTTPBasicCredentials = Depends(basic_auth)):
    """Runs before every page and API route. Wrong or missing login -> 401 (the browser asks again)."""
    # compare_digest takes the same time whether the first letter or the last letter is wrong,
    # so nobody can guess the password one character at a time by timing the replies
    username_ok = secrets.compare_digest(credentials.username.encode("utf-8"), APP_USERNAME.encode("utf-8"))
    password_ok = secrets.compare_digest(credentials.password.encode("utf-8"), APP_PASSWORD.encode("utf-8"))
    if not (username_ok and password_ok):
        raise HTTPException(status_code=401, detail="Wrong username or password",
                            headers={"WWW-Authenticate": "Basic"})


# dependencies=[...] puts require_login in front of EVERY route.
# The automatic /docs pages are switched off, because they'd skip the login.
app = FastAPI(dependencies=[Depends(require_login)], lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")      # CSS only - fine without a login
templates = Jinja2Templates(directory="templates")


def short_url(url):
    """'https://www.linkedin.com/in/kai/' -> 'linkedin.com/in/kai' - readable when printed on paper."""
    text = url or ""
    without_protocol = text.split("//")[-1]               # drop "https://"
    without_www = without_protocol.removeprefix("www.")
    return without_www.rstrip("/")


templates.env.filters["short_url"] = short_url            # lets templates write {{ url|short_url }}


def static_url(file_name):
    """'/static/style.css?v=1731783456' - the number is when the file was last saved.
    Browsers keep old copies of CSS files; a new number after every save makes them fetch the new one."""
    last_saved = int(os.path.getmtime(os.path.join("static", file_name)))
    return f"/static/{file_name}?v={last_saved}"


templates.env.globals["static_url"] = static_url          # lets templates write {{ static_url("style.css") }}


def get_jobs(city=None, days=None, applied=None):
    """Return the jobs that match the filters, newest first."""
    # LEFT JOIN applied_companies: applied_at is a date if I've applied to that company, otherwise NULL
    sql = """SELECT jobs.source_job_id, jobs.title, jobs.company_name, jobs.company_website, jobs.place,
                    jobs.date_posted, jobs.link, applied_companies.applied_at
             FROM jobs
             LEFT JOIN applied_companies ON jobs.company_name = applied_companies.company_name"""
    conditions = []
    values = []

    if city:
        conditions.append("jobs.place = ?")
        values.append(city)

    if days is not None:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        conditions.append("jobs.date_posted >= ?")
        values.append(cutoff)

    if applied == "yes":
        conditions.append("applied_companies.applied_at IS NOT NULL")
    elif applied == "no":
        conditions.append("applied_companies.applied_at IS NULL")

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY jobs.date_posted DESC"

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(sql, values).fetchall()
    connection.close()
    return [dict(row) for row in rows]


@app.get("/jobs")
def show_jobs(request: Request, city: str = None, days: str = None, applied: str = None):
    """The job list, e.g. /jobs?city=London&days=7&applied=no"""
    # days arrives as text from the URL - turn it into a number, or None if it's empty
    if days:
        days_number = int(days)
    else:
        days_number = None

    # Only "yes" and "no" mean something - ignore anything else
    if applied not in ("yes", "no"):
        applied = None

    jobs = get_jobs(city, days_number, applied)
    return templates.TemplateResponse(request, "jobs.html",
                                      {"jobs": jobs, "city": city, "days": days_number, "applied": applied})


@app.get("/jobs/{source_job_id}")
def show_job(request: Request, source_job_id: str):
    """One job's detail page, with its saved company LinkedIn URL (if any) and applied date (if any)."""
    sql = """SELECT jobs.source_job_id, jobs.title, jobs.company_name, jobs.company_website,
                    jobs.place, jobs.date_posted, jobs.link,
                    contact_lookups.company_linkedin_url, applied_companies.applied_at
             FROM jobs
             LEFT JOIN contact_lookups ON jobs.company_name = contact_lookups.company_name
             LEFT JOIN applied_companies ON jobs.company_name = applied_companies.company_name
             WHERE jobs.source_job_id = ?"""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    row = connection.execute(sql, (source_job_id,)).fetchone()
    connection.close()

    if row is None:
        return PlainTextResponse("Job not found", status_code=404)
    return templates.TemplateResponse(request, "job_detail.html", {"job": dict(row)})


@app.post("/jobs/{source_job_id}/applied")
def toggle_applied(request: Request, source_job_id: str):
    """'Mark as applied' button: adds the company if it isn't saved yet, removes it if it is (undo)."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    row = connection.execute(
        "SELECT company_name FROM jobs WHERE source_job_id = ?", (source_job_id,)).fetchone()
    if not row:
        connection.close()
        return PlainTextResponse("Job not found", status_code=404)

    company_name = row[0]
    already_applied = connection.execute(
        "SELECT 1 FROM applied_companies WHERE company_name = ?", (company_name,)).fetchone()
    if already_applied:
        connection.execute("DELETE FROM applied_companies WHERE company_name = ?", (company_name,))
    else:
        connection.execute("INSERT INTO applied_companies (company_name, applied_at) VALUES (?, ?)",
                           (company_name, date.today().isoformat()))
    connection.commit()
    connection.close()

    # 303 tells the browser to GET the job page again; the query string keeps my list filters
    job_page = f"/jobs/{source_job_id}"
    query = request.url.query
    if query:
        job_page += f"?{query}"
    return RedirectResponse(job_page, status_code=303)


@app.get("/summary")
def show_summary(company: str):
    """The company summary on the detail page (cached after the first OpenAI call)."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    sql = "SELECT company_name, company_website, description FROM jobs WHERE company_name = ? LIMIT 1"
    row = connection.execute(sql, (company,)).fetchone()
    connection.close()

    summary = get_summary(row["company_name"], row["company_website"], row["description"])
    return {"summary": summary}


@app.get("/contacts")
def show_contacts(company: str):
    """'Find decision makers' button. Returns {"error": ..., "contacts": [...]}."""
    # Get the company's website from its job listing
    connection = sqlite3.connect(DATABASE_PATH)
    row = connection.execute(
        "SELECT company_website FROM jobs WHERE company_name = ? LIMIT 1", (company,)).fetchone()
    connection.close()

    if row:
        website = row[0]
    else:
        website = None

    # A NEW lookup costs Blitz records, so it counts towards today's cap. Saved contacts are free.
    # (With no website, Blitz is never called, so there's nothing to count.)
    is_new_lookup = website and not has_contact_lookup(company)
    if is_new_lookup and not use_daily_allowance("contacts", company, MAX_CONTACT_LOOKUPS_PER_DAY):
        return {"error": True, "limit_reached": True, "contacts": [],
                "message": "Daily lookup limit reached - try again tomorrow."}

    try:
        people = get_decision_makers(company, website)
    except Exception as error:
        print(f"Contact lookup failed for {company}: {error}")
        return {"error": True, "contacts": []}
    return {"error": False, "contacts": people}


@app.get("/jobs/{source_job_id}/plan")
def show_plan(request: Request, source_job_id: str, refresh: bool = False):
    """The prospecting plan. ?refresh=true rebuilds it (costs money and discards my edits)."""
    connection = sqlite3.connect(DATABASE_PATH)
    row = connection.execute(
        "SELECT company_name, company_website, place, title FROM jobs WHERE source_job_id = ?",
        (source_job_id,)).fetchone()
    connection.close()
    if not row:
        return PlainTextResponse("Job not found.", status_code=404)

    company_name, website, place, job_title = row

    # Building a plan costs money (Exa, OpenAI, Blitz), so new builds count towards today's cap.
    # Viewing a saved plan is free and never counts. (No website = get_pack stops before any API call.)
    needs_build = refresh or not has_saved_pack(company_name)
    if needs_build and website and not use_daily_allowance("plan", company_name, MAX_PLANS_PER_DAY):
        return templates.TemplateResponse(request, "limit_reached.html",
                                          {"source_job_id": source_job_id}, status_code=429)

    territory = territory_for(place, job_title)                     # e.g. "EMEA" from "SDR, EMEA"
    try:
        pack = get_pack(company_name, website, territory, refresh=refresh)
    except Exception as error:
        print(f"Plan failed for {company_name}: {error}")
        return PlainTextResponse("Couldn't build the plan - try again in a minute.", status_code=500)

    if refresh:
        # Send the browser to the plain URL, so reloading the page doesn't pay for another rebuild
        return RedirectResponse(f"/jobs/{source_job_id}/plan", status_code=303)

    return templates.TemplateResponse(request, "plan.html", {
        "pack": pack,
        "source_job_id": source_job_id,
        "edited_html": get_edited_html(company_name),
    })


@app.post("/jobs/{source_job_id}/plan/edits")
async def save_plan_edits(request: Request, source_job_id: str):
    """'Save edits' on the plan page sends the edited HTML here as {"html": "..."}."""
    data = await request.json()

    html = None
    if isinstance(data, dict):
        html = data.get("html")

    is_valid = isinstance(html, str) and html.strip() != "" and len(html) <= MAX_EDIT_SIZE
    if not is_valid:
        return JSONResponse({"ok": False, "error": "Nothing to save, or edit too large"}, status_code=400)

    connection = sqlite3.connect(DATABASE_PATH)
    row = connection.execute(
        "SELECT company_name FROM jobs WHERE source_job_id = ?", (source_job_id,)).fetchone()
    connection.close()
    if not row:
        return JSONResponse({"ok": False, "error": "Job not found"}, status_code=404)

    company_name = row[0]
    save_edited_html(company_name, html)
    return {"ok": True}
