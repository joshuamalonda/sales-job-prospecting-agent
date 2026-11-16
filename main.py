import sqlite3                                   # Python's built-in SQLite database module
from datetime import date, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles      # serves the files in the static/ folder (CSS)
from fastapi.templating import Jinja2Templates   # fills the HTML templates with data

from contacts import create_contacts_tables, get_decision_makers
from prospecting import create_packs_table, get_edited_html, get_pack, save_edited_html, territory_for
from summaries import create_summaries_table, get_summary

DATABASE = "landly.db"
MAX_EDIT_SIZE = 500_000          # characters - a saved plan edit bigger than this is rejected


def create_applied_table():
    """Companies I've applied to (one row per company, so every job at that company shows as applied)."""
    connection = sqlite3.connect(DATABASE)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS applied_companies (
            company_name TEXT UNIQUE,
            applied_at TEXT
        )
    """)
    connection.commit()
    connection.close()


# Make sure every table exists before the app starts
create_packs_table()
create_contacts_tables()
create_summaries_table()
create_applied_table()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def short_url(url):
    """'https://www.linkedin.com/in/kai/' -> 'linkedin.com/in/kai' - readable when printed on paper."""
    text = url or ""
    without_protocol = text.split("//")[-1]               # drop "https://"
    without_www = without_protocol.removeprefix("www.")
    return without_www.rstrip("/")


templates.env.filters["short_url"] = short_url            # lets templates write {{ url|short_url }}


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

    connection = sqlite3.connect(DATABASE)
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
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    row = connection.execute(sql, (source_job_id,)).fetchone()
    connection.close()

    if row is None:
        return PlainTextResponse("Job not found", status_code=404)
    return templates.TemplateResponse(request, "job_detail.html", {"job": dict(row)})


@app.post("/jobs/{source_job_id}/applied")
def toggle_applied(request: Request, source_job_id: str):
    """'Mark as applied' button: adds the company if it isn't saved yet, removes it if it is (undo)."""
    connection = sqlite3.connect(DATABASE, timeout=30)
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
    connection = sqlite3.connect(DATABASE)
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
    connection = sqlite3.connect(DATABASE)
    row = connection.execute(
        "SELECT company_website FROM jobs WHERE company_name = ? LIMIT 1", (company,)).fetchone()
    connection.close()

    if row:
        website = row[0]
    else:
        website = None

    try:
        people = get_decision_makers(company, website)
    except Exception as error:
        print(f"Contact lookup failed for {company}: {error}")
        return {"error": True, "contacts": []}
    return {"error": False, "contacts": people}


@app.get("/jobs/{source_job_id}/plan")
def show_plan(request: Request, source_job_id: str, refresh: bool = False):
    """The prospecting plan. ?refresh=true rebuilds it (costs money and discards my edits)."""
    connection = sqlite3.connect(DATABASE)
    row = connection.execute(
        "SELECT company_name, company_website, place, title FROM jobs WHERE source_job_id = ?",
        (source_job_id,)).fetchone()
    connection.close()
    if not row:
        return PlainTextResponse("Job not found.", status_code=404)

    company_name, website, place, job_title = row
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

    connection = sqlite3.connect(DATABASE)
    row = connection.execute(
        "SELECT company_name FROM jobs WHERE source_job_id = ?", (source_job_id,)).fetchone()
    connection.close()
    if not row:
        return JSONResponse({"ok": False, "error": "Job not found"}, status_code=404)

    company_name = row[0]
    save_edited_html(company_name, html)
    return {"ok": True}
