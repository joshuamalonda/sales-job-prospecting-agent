import os
import sqlite3
from datetime import date

import requests
from dotenv import load_dotenv

load_dotenv()
BLITZ_KEY = os.getenv("BLITZAPI_KEY")
BASE_URL = "https://api.blitz-api.ai"
HEADERS = {"x-api-key": BLITZ_KEY, "Content-Type": "application/json"}
DATABASE = "landly.db"

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
    connection = sqlite3.connect(DATABASE)
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


def get_saved_contacts(connection, company_name):
    """Read a company's saved decision makers from the database."""
    rows = connection.execute(
        "SELECT full_name, title, linkedin_url, tier FROM contacts WHERE company_name = ? ORDER BY tier",
        (company_name,)).fetchall()
    return [dict(row) for row in rows]


def get_decision_makers(company_name, company_website):
    """Cache first. Otherwise: website -> LinkedIn -> people waterfall -> save -> return.
    Errors are raised (and nothing saved) so the lookup can be retried."""
    connection = sqlite3.connect(DATABASE, timeout=30)
    connection.row_factory = sqlite3.Row

    # Already searched this company - return what we saved (no records used)
    looked_up = connection.execute(
        "SELECT 1 FROM contact_lookups WHERE company_name = ?", (company_name,)).fetchone()
    if looked_up:
        contacts = get_saved_contacts(connection, company_name)
        connection.close()
        return contacts

    # Slow API calls - no database write is open during these
    company_linkedin_url = None
    if company_website:
        company_linkedin_url = domain_to_linkedin(company_website)

    results = []
    if company_linkedin_url:
        results = find_decision_makers(company_linkedin_url)

    # Save: the lookup itself, then each person
    today = date.today().isoformat()
    connection.execute(
        "INSERT OR IGNORE INTO contact_lookups (company_name, company_linkedin_url, checked_at) "
        "VALUES (?, ?, ?)",
        (company_name, company_linkedin_url, today))
    for result in results:
        person = result["person"]

        # Their current job title is the first entry in their work history
        title = ""
        if person.get("experiences"):
            title = person["experiences"][0]["job_title"]

        tier = result["icp"]                          # which TITLE_TIERS group matched (lower = better)
        connection.execute(
            "INSERT OR IGNORE INTO contacts (company_name, full_name, title, linkedin_url, tier, found_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (company_name, person.get("full_name"), title, person.get("linkedin_url"), tier, today))
    connection.commit()

    contacts = get_saved_contacts(connection, company_name)
    connection.close()
    return contacts