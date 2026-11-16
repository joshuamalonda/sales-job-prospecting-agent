import os
import sqlite3
from datetime import date

import requests

from settings import DATABASE_PATH

BLITZ_KEY = os.getenv("BLITZAPI_KEY")
BASE_URL = "https://api.blitz-api.ai"
HEADERS = {"x-api-key": BLITZ_KEY, "Content-Type": "application/json"}

# Job titles to look for, in priority order (best match first)
TITLE_TIERS = [
    {"include_title": ["Head of Sales Development", "Sales Development Manager",
                       "SDR Manager", "BDR Manager", "Director of Sales Development"],
     "exclude_title": ["assistant", "intern", "junior"]},
    {"include_title": ["VP Sales", "Head of Sales", "Sales Director",
                       "Chief Revenue Officer", "VP Revenue"],
     "exclude_title": ["assistant", "intern", "junior", "operations"]},
    {"include_title": ["Talent Acquisition", "Recruiter"],
     "exclude_title": ["intern", "coordinator"]},
    {"include_title": ["CEO", "Founder", "Co-founder"],
     "exclude_title": ["assistant"]},
]

# Where to look, in order: UK, then Europe (biggest tech hubs first), then US
# Blitz allows max 10 countries per region
REGIONS = [
    ("UK", ["GB"]),
    ("Europe", ["IE", "NL", "DE", "FR", "ES", "SE", "DK", "BE", "CH", "PT"]),
    ("Europe (rest)", ["IT", "NO", "FI", "AT", "PL"]),
    ("US", ["US"]),
]


def build_cascade(countries):
    """Same title tiers, restricted to one region's countries."""
    cascade = []
    for tier in TITLE_TIERS:
        tier_with_location = dict(tier)               # a copy, so TITLE_TIERS itself never changes
        tier_with_location["location"] = countries
        cascade.append(tier_with_location)
    return cascade


def find_decision_makers(company_linkedin_url, max_results=3):
    """Waterfall by region: UK, then Europe, then US. Stops at the first region with results.
    Only people returned cost records, so empty regions are free."""
    for region, countries in REGIONS:
        payload = {
            "company_linkedin_url": company_linkedin_url,
            "cascade": build_cascade(countries),
            "max_results": max_results,
        }
        response = requests.post(f"{BASE_URL}/v2/search/waterfall-icp-keyword",
                                 headers=HEADERS, json=payload, timeout=60)
        if response.status_code != 200:
            raise RuntimeError(f"Blitz people search failed: {response.status_code} {response.text}")
        results = response.json()["results"]
        if results:
            print(f"Found {len(results)} decision makers in {region}")
            return results
    return []


def create_contacts_tables():
    """contact_lookups = one row per company we've searched.
    contacts = the people found (one company -> many people)."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS contact_lookups (
            company_name TEXT UNIQUE,
            company_linkedin_url TEXT,
            checked_at TEXT
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            company_name TEXT,
            full_name TEXT,
            title TEXT,
            linkedin_url TEXT,
            tier INTEGER,
            email TEXT,
            found_at TEXT,
            UNIQUE(company_name, linkedin_url)
        )
    """)
    connection.commit()
    connection.close()


def domain_to_linkedin(domain):
    """Website -> company LinkedIn URL (1 record). None if Blitz has no match.
    Raises an error if the request itself failed."""
    response = requests.post(f"{BASE_URL}/v2/enrichment/domain-to-linkedin",
                             headers=HEADERS, json={"domain": domain}, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"Blitz domain lookup failed: {response.status_code} {response.text}")
    data = response.json()
    if data.get("found"):
        return data["company_linkedin_url"]
    return None


def simplify_url(url):
    """'https://www.LinkedIn.com/company/acme/' -> 'linkedin.com/company/acme', so two ways of
    writing the same address compare as equal."""
    text = (url or "").strip().lower()
    text = text.split("//")[-1]                       # drop "https://"
    text = text.removeprefix("www.")
    return text.rstrip("/")


def current_job_title(person, company_linkedin_url, company_website):
    """The person's job title at the company we searched - but only if they STILL work there.
    Returns None if they've left (Blitz can return ex-employees), so the caller can skip them.

    Blitz gives each person a list of "experiences" (jobs). Each one has job_is_current (true/false)
    and the company's company_linkedin_url and company_domain."""
    current_jobs = []
    for experience in person.get("experiences") or []:
        if experience.get("job_is_current") is True:
            current_jobs.append(experience)
    if not current_jobs:
        return None

    searched_linkedin = simplify_url(company_linkedin_url)
    searched_domain = simplify_url(company_website).split("/")[0]       # "acme.com/about" -> "acme.com"

    for job in current_jobs:
        job_linkedin = simplify_url(job.get("company_linkedin_url"))
        job_domain = simplify_url(job.get("company_domain")).split("/")[0]
        if searched_linkedin and job_linkedin == searched_linkedin:
            return job.get("job_title") or ""
        if searched_domain and job_domain == searched_domain:
            return job.get("job_title") or ""

    # If Blitz didn't say which company any current job is at, we can't check - trust the first current job
    has_company_details = False
    for job in current_jobs:
        if job.get("company_linkedin_url") or job.get("company_domain"):
            has_company_details = True
    if not has_company_details:
        return current_jobs[0].get("job_title") or ""

    return None                                        # current job is somewhere else - they've left


def has_contact_lookup(company_name):
    """True if we've already looked this company up (so showing its contacts is free)."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    row = connection.execute(
        "SELECT 1 FROM contact_lookups WHERE company_name = ?", (company_name,)).fetchone()
    connection.close()
    return row is not None


def get_saved_contacts(company_name):
    """Read a company's saved decision makers from the database."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT full_name, title, linkedin_url, tier FROM contacts WHERE company_name = ? ORDER BY tier",
        (company_name,)).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def get_decision_makers(company_name, company_website):
    """Cache first. Otherwise: website -> LinkedIn -> people waterfall -> save -> return.
    Errors are raised (and nothing saved) so the lookup can be retried."""
    # Already searched this company - return what we saved (no records used)
    if has_contact_lookup(company_name):
        return get_saved_contacts(company_name)

    # Slow API calls - no database connection is open during these
    company_linkedin_url = None
    if company_website:
        company_linkedin_url = domain_to_linkedin(company_website)

    results = []
    if company_linkedin_url:
        results = find_decision_makers(company_linkedin_url)

    # Save: the lookup itself, then each person who still works there
    today = date.today().isoformat()
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.execute(
        "INSERT OR IGNORE INTO contact_lookups (company_name, company_linkedin_url, checked_at) "
        "VALUES (?, ?, ?)",
        (company_name, company_linkedin_url, today))
    for result in results:
        person = result["person"]
        title = current_job_title(person, company_linkedin_url, company_website)
        if title is None:
            print(f"Skipped {person.get('full_name')}: no current job at {company_name}")
            continue

        tier = result["icp"]                          # which TITLE_TIERS group matched (lower = better)
        connection.execute(
            "INSERT OR IGNORE INTO contacts (company_name, full_name, title, linkedin_url, tier, found_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (company_name, person.get("full_name"), title, person.get("linkedin_url"), tier, today))
    connection.commit()
    connection.close()
    return get_saved_contacts(company_name)