import json
import sqlite3
from datetime import date

# job_file is the opened file. Its contents are JSON text, and json.load turns that into Python dicts and lists
def load_jobs(file_name):
    with open(file_name) as job_file:
        job_data = json.load(job_file)
    return job_data

raw_jobs = load_jobs("jobs_all.json")
print(len(raw_jobs))

def clean_jobs(raw_jobs):
    today = date.today().isoformat()
    all_cleaned_jobs = []
    for job in raw_jobs:
        locations = job["locations"]
        # If the job has locations, use the first one's city (or country if no city)
        if locations:
            place = job["locations"][0]["city"]
            if place is None:
                place = job["locations"][0]["country"]
        # If the job has no locations at all, avoid a crash
        else:
            place = "Unknown"

        clean_job = {
            "title": job["title"],
            "company_name": job["company"]["name"],
            "place": place,
            "company_website": job["company"]["website"],
            "description": job["description"],
            "source_job_id": job["id"],
            "locations": job["locations"],
            "date_posted": job["date_posted"],
            "source": job["source"],
            "link": job["listing_url"],
            "first_seen": today,
            "last_seen": today,
            "occupation_id": job["occupation"]["id"],
            "company_categories": job["company"]["categories"],
            "company_industries": job["company"]["industries"]
        }
        all_cleaned_jobs.append(clean_job)
    return all_cleaned_jobs

cleaned = clean_jobs(raw_jobs)
print(len(cleaned))

# Keep only SDR/BDR roles. Catches non-SDR jobs the title search lets through
def keep_only_sdrs(cleaned):
    kept_jobs = []
    rejected_jobs = []
    for job in cleaned:
         occupation_id = job["occupation_id"]
         job_title = job["title"].lower()
         id_matches = occupation_id == "jobo:sales-development-representative"
         title_matches = "sales development representative" in job_title or "business development representative" in job_title
         is_manager = "manager" in job_title
         if id_matches or (title_matches and not is_manager):
             kept_jobs.append(job)
         else:
            job["rejection_reason"] = "not sdr"
            rejected_jobs.append(job)
    return kept_jobs, rejected_jobs

kept_sdrs, reject_sdrs = keep_only_sdrs(cleaned)
print(len(kept_sdrs))
print(len(reject_sdrs))

# Industries that count as tech "Research & Development" left out, Jobo tags non-tech firms with it
def keep_tech_jobs(kept_sdrs):
    tech_jobs = []
    rejected_jobs = []
    tech_industries = ["Software", "Custom Software & IT Services", "Security Products & Services", "Credit Cards & Transaction Processing"]
    for job in kept_sdrs:
       company_category = job["company_categories"]
       company_industry = job["company_industries"]
       has_tech_industries = False
       for industry in company_industry:
           if industry in tech_industries:
               has_tech_industries = True
               break
       if "saas" in company_category or has_tech_industries:
           tech_jobs.append(job)
       else:
           job["rejection_reason"] = "not tech"
           rejected_jobs.append(job)
    return tech_jobs, rejected_jobs

tech_jobs, not_tech = keep_tech_jobs(kept_sdrs)
print(len(tech_jobs))
print(len(not_tech))

def remove_agencies(tech_jobs):
    agency_names = ["Lifelancer", "ManpowerGroup Talent Solutions", "Talent Solutions", "Excelerate360", "Huzzle"]
    agency_phrases = ["curated by", "on behalf of our client"]

    final_jobs = []
    rejected_jobs = []
# DO: SentinelOne has no categories or industries, so it's wrongly rejected
    for job in tech_jobs:
        company_name = job["company_name"]
        description = job["description"]
    # Lowercase so "Curated by" and "curated by" both match
        description = description.lower()
        has_agency_phrase = False
        for agency_phrase in agency_phrases:
            if agency_phrase in description:
                has_agency_phrase = True
                break
        if company_name in agency_names or has_agency_phrase:
            job["rejection_reason"] = "is an agency"
            rejected_jobs.append(job)
        else:
            final_jobs.append(job)
    return rejected_jobs, final_jobs

rejected_jobs, final_jobs = remove_agencies(tech_jobs)
print(len(final_jobs))
print(len(rejected_jobs))

# Created a new variable that includes all of the rejected jobs from all the filters above
total_rejected_jobs = reject_sdrs + not_tech + rejected_jobs

print(len(total_rejected_jobs))

# Using a for loop to display the reason why each company was rejected
for job in total_rejected_jobs:
    print(job["company_name"], job["rejection_reason"])

# Saves a list of jobs to a JSON file
def save_jobs(jobs, file_name):
    with open(file_name, "w") as job_file:
        json.dump(jobs, job_file, indent=2)

save_jobs(total_rejected_jobs, "rejected_jobs.json")

def remove_duplicates(final_jobs):
    kept = [] # jobs you keep
    rejected_jobs = [] # duplicates
    seen = set() # fingerprints you’ve already kept, like a guest list at a door
    for job in final_jobs:
        url = job["company_website"]
        if url is None:
            url = job["company_name"]
        url = url.lower()
        url = url.replace("https://", "")
        url = url.replace("http://", "")
        url = url.replace("www.", "")
        url = url.split("/")[0]

        key = (url, job["title"].lower(), job["place"])
        if key in seen:
           job["rejection_reason"] = "duplicate"
           rejected_jobs.append(job)
        else:
           seen.add(key)
           kept.append(job)
    return rejected_jobs, kept


duplicate_jobs, unique_jobs = remove_duplicates(final_jobs)
print(len(unique_jobs))
print(len(duplicate_jobs))

total_rejected_jobs = reject_sdrs + not_tech + rejected_jobs + duplicate_jobs
print(len(total_rejected_jobs))


def create_database():
     # Opens the database file (creates it if it doesn't exist)

    connection = sqlite3.connect("landly.db")

    # Creates the jobs table, if it isn't there already
    connection.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            source_job_id   TEXT UNIQUE,
            title           TEXT,
            company_name    TEXT,
            company_website TEXT,
            place           TEXT,
            description     TEXT,
            date_posted     TEXT,
            source          TEXT,
            link            TEXT,
            first_seen      TEXT,
            last_seen       TEXT
        )
    """)

# Saves the change to the file
    connection.commit()
    connection.close()

create_database()

# Saves a list of jobs into the jobs table, & now it uses upsert to insert new jobs and update last seen if the job is already in the database
def save_to_database(unique_jobs):
    connection = sqlite3.connect("landly.db")
    for job in unique_jobs:
        connection.execute("""
            INSERT INTO jobs (
                source_job_id, title, company_name, company_website, place,
                description, date_posted, source, link, first_seen, last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_job_id) DO UPDATE SET
                last_seen = excluded.last_seen
        """, (
            job["source_job_id"], job["title"], job["company_name"],
            job["company_website"], job["place"], job["description"],
            job["date_posted"], job["source"], job["link"],
            job["first_seen"], job["last_seen"]
        ))
    connection.commit()
    connection.close()

# Counts how many jobs are in the database
def count_jobs_in_database():
    connection = sqlite3.connect("landly.db")
    result = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()
    connection.close()
    return result[0]

save_to_database(unique_jobs)
print(count_jobs_in_database())

