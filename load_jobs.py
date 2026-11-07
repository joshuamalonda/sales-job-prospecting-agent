import json
from datetime import date

# job_file is the opened file. Its contents are JSON text, and json.load turns that into Python dicts and lists
def load_jobs(file_name):
    with open(file_name) as job_file:
        job_data = json.load(job_file)
    return job_data["jobs"]

raw_jobs = load_jobs("jobs_page1.json")
print(len(raw_jobs))

# For loop that transforms the data into our clean dictionary, then adds all the cleaned jobs to the cleaned jobs list above

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
         if occupation_id == "jobo:sales-development-representative":
             kept_jobs.append(job)
         else:
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
           rejected_jobs.append(job)
    return tech_jobs, rejected_jobs

tech_jobs, rejected_jobs = keep_tech_jobs(kept_sdrs)
print(len(tech_jobs))
print(len(rejected_jobs))

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
            rejected_jobs.append(job)
        else:
            final_jobs.append(job)
    return rejected_jobs, final_jobs

rejected_jobs, final_jobs = remove_agencies(tech_jobs)
print(len(final_jobs))
print(len(rejected_jobs))




