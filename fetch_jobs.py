import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("RAPIDAPI_KEY")


headers = {"x-rapidapi-key": api_key,
           "x-rapidapi-host": "ats-jobs-db.p.rapidapi.com"
           }


params = {"q" : '"Sales Development Representative"',
          "location" : "United Kingdom",
          "posted_after" : "2026-10-10",
          "employment_type" : "full-time",
          "search_description" : "false",
          "page_size" : "100",
          "page" : "1",
          "include_facets" : "",
          "include_fields": "description"
          }

response = requests.get("https://ats-jobs-db.p.rapidapi.com/api/jobs", headers=headers, params=params)
if response.status_code == 200:
    data = response.json()
    print(data["total"], data["total_pages"], len(data["jobs"]))

    # Save the response so we can test without calling the API again (caching)
    with open("jobs_sdr_page1.json", "w") as job_file:
        json.dump(data, job_file, indent=2)
else:
    print(response.status_code)
    print(response.text)