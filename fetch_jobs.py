import os # operating system (computer environment)
import requests # Library for sending HTTP requests (GET, POST etc.) to APIs
import json
from dotenv import load_dotenv # Loads the variables in .env so os.getenv can read them

load_dotenv()
api_key = os.getenv("RAPIDAPI_KEY") # Gets the API key from the env file

# Headers: my API key (proves I'm allowed in) and which API on RapidAPI I'm calling
headers = {"x-rapidapi-key": api_key,
           "x-rapidapi-host": "ats-jobs-db.p.rapidapi.com"
           }

url = "https://ats-jobs-db.p.rapidapi.com/api/jobs"


# Fetches every page of results for one search, and returns all the jobs in one list, the params allows us to get the data we need from the API
def fetch_all_pages(search_term): # Search term could be SDR or BDR
    params = {
        "q": '"' + search_term + '"',
        "location": "United Kingdom",
        "posted_after": "2026-10-10",
        "employment_type": "full-time",
        "search_description": "false",
        "include_fields": "description",
        "include_facets": "",
        "page_size": "100",
        "page": "1",
    }

    all_jobs = []

    # Page 1: if successful, add its jobs to all_jobs and read how many pages there are
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print(response.status_code, response.text)
        return all_jobs
    data = response.json()
    all_jobs.extend(data["jobs"])
    total_pages = data["total_pages"]

    # Pages 2 onwards (only if there's more than 1 page): add each page's jobs to all_jobs
    for page in range(2, total_pages + 1):
        params["page"] = str(page)
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(response.status_code, response.text)
            break
        data = response.json()
        all_jobs.extend(data["jobs"])

    return all_jobs

# Fetches SDR and BDR jobs from the API and caches them in jobs_all.json
def fetch_and_save():
    sdr_jobs = fetch_all_pages("Sales Development Representative")
    bdr_jobs = fetch_all_pages("Business Development Representative")
    combined_jobs = sdr_jobs + bdr_jobs
    print(len(sdr_jobs), len(bdr_jobs), len(combined_jobs))
    with open("jobs_all.json", "w") as job_file:
        json.dump(combined_jobs, job_file, indent=2)

