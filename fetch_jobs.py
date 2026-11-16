import os # operating system (computer environment)
import requests # Library for sending HTTP requests (GET, POST etc.# ) to APIs
import json
from dotenv import load_dotenv # Loads the variables in .env so os.getenv can read them
from datetime import date, timedelta # importing date and time

load_dotenv()
api_key = os.getenv("RAPIDAPI_KEY") # Gets the API key from the env file

# Headers: my API key (proves I'm allowed in) and which API on RapidAPI I'm calling
headers = {"x-rapidapi-key": api_key,
           "x-rapidapi-host": "ats-jobs-db.p.rapidapi.com"
           }

url = "https://ats-jobs-db.p.rapidapi.com/api/jobs"

NORMAL_DAYS_BACK = 2         # the normal daily fetch: postings from the last 2 days
MAX_PAGES_PER_SEARCH = 5     # safety cap: never more than 5 requests (500 jobs) per search, even on a backfill


# Fetches every page of results for one search, and returns all the jobs in one list, the params allows us to get the data we need from the API
def fetch_all_pages(search_term, days_back): # Search term could be SDR or BDR
    posted_after = (date.today() - timedelta(days=days_back)).isoformat()
    params = {
        "q": '"' + search_term + '"',
        "location": "United Kingdom",
        "posted_after": posted_after,
        "employment_type": "full-time",
        "search_description": "false",
        "include_fields": "description",
        "include_facets": "",
        "page_size": "100",
        "page": "1",
    }

    all_jobs = []
    page = 1
    total_pages = 1

    # Each page is one API request (100 jobs). The first answer says how many pages there are.
    while page <= total_pages and page <= MAX_PAGES_PER_SEARCH:
        params["page"] = str(page)
        response = requests.get(url, headers=headers, params=params, timeout=60)
        if response.status_code != 200:
            # Raise instead of returning half the jobs, so a failed fetch is never counted as a successful run
            raise RuntimeError(f"Jobs API failed on page {page} of '{search_term}': "
                               f"{response.status_code} {response.text[:200]}")
        data = response.json()
        all_jobs.extend(data["jobs"])
        total_pages = data.get("total_pages") or 1
        print(f"'{search_term}': page {page} of {total_pages} ({data.get('total')} jobs in total)")
        page += 1

    if total_pages > MAX_PAGES_PER_SEARCH:
        print(f"Stopped at {MAX_PAGES_PER_SEARCH} pages for '{search_term}' (safety cap) - "
              f"{total_pages - MAX_PAGES_PER_SEARCH} page(s) not fetched")
    return all_jobs


# Fetches SDR and BDR jobs from the API and caches them in jobs_all.json
def fetch_and_save(days_back=NORMAL_DAYS_BACK):
    sdr_jobs = fetch_all_pages("Sales Development Representative", days_back)
    bdr_jobs = fetch_all_pages("Business Development Representative", days_back)
    combined_jobs = sdr_jobs + bdr_jobs
    print(len(sdr_jobs), len(bdr_jobs), len(combined_jobs))
    with open("jobs_all.json", "w") as job_file:
        json.dump(combined_jobs, job_file, indent=2)

