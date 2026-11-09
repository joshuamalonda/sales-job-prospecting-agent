import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("RAPIDAPI_KEY")


headers = {"x-rapidapi-key": api_key,
           "x-rapidapi-host": "ats-jobs-db.p.rapidapi.com"
           }

url = "https://ats-jobs-db.p.rapidapi.com/api/jobs"


# Fetches every page of results for one search, and returns all the jobs in one list
def fetch_all_pages(search_term):
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

    # Page 1: also tells us how many pages there are
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print(response.status_code, response.text)
        return all_jobs
    data = response.json()
    all_jobs.extend(data["jobs"])
    total_pages = data["total_pages"]

    # Pages 2 onwards
    for page in range(2, total_pages + 1):
        params["page"] = str(page)
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(response.status_code, response.text)
            break
        data = response.json()
        all_jobs.extend(data["jobs"])

    return all_jobs


sdr_jobs = fetch_all_pages("Sales Development Representative")
print(len(sdr_jobs))

with open("jobs_sdr.json", "w") as job_file:
    json.dump(sdr_jobs, job_file, indent=2)