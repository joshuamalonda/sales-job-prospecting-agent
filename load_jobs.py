import json
from datetime import date

# job_file is the opened file. Its contents are JSON text, and json.load turns that into Python dicts and lists
with open("jobs_page1.json") as job_file:
    job_data = json.load(job_file)

# A list that will store all of the job data we will transform into our own data model using a dictionary
all_cleaned_jobs = []

# Works out today's date
today = date.today().isoformat()

# For loop that transforms the data into our clean dictionary, then adds all the cleaned jobs to the cleaned jobs list above
for job in job_data["jobs"]:
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
       "title" : job["title"],
       "company_name" : job["company"]["name"],
       "place" : place,
       "company_website" : job["company"]["website"],
       "description" : job["description"],
       "source_job_id" : job["id"],
       "locations" : job["locations"],
       "date_posted" : job["date_posted"],
       "source" : job["source"],
       "link" : job["listing_url"],
       "first_seen" : today,
       "last_seen" : today,
       "occupation_id" : job["occupation"]["id"],
       "company_categories" : job["company"]["categories"],
       "company_industries" : job["company"]["industries"]
}
    all_cleaned_jobs.append(clean_job)

# Keep only SDR/BDR roles. Catches non-SDR jobs the title search lets through
kept_jobs = []

rejected_jobs = []

for job in all_cleaned_jobs:
    occupation_id = job["occupation_id"]
    if occupation_id == "jobo:sales-development-representative":
        kept_jobs.append(job)
    else:
        rejected_jobs.append(job)

# Industries that count as tech "Research & Development" left out, Jobo tags non-tech firms with it
tech_jobs = []

tech_industries = ["Software", "Custom Software & IT Services", "Security Products & Services", "Credit Cards & Transaction Processing"]
for job in kept_jobs:
    company_category = job["company_categories"]
    company_industry = job["company_industries"]
    # Flag: assume no match, flip to True if any industry is on the tech list
    has_tech_industries = False
    for industry in company_industry:
        if industry in tech_industries:
            has_tech_industries = True
            break
    if "saas" in company_category or has_tech_industries:
        tech_jobs.append(job)
    else:
        rejected_jobs.append(job)

# Precise phrases only. "our client" wrongly matched real companies describing their customers
agency_names = ["Lifelancer", "ManpowerGroup Talent Solutions", "Talent Solutions", "Excelerate360", "Huzzle"]
agency_phrases = ["curated by", "on behalf of our client"]

final_jobs = []
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
print(len(final_jobs))
print(len(rejected_jobs))

print(len(all_cleaned_jobs))
print(all_cleaned_jobs[0])

print(all_cleaned_jobs[0]["occupation_id"])
print(all_cleaned_jobs[0]["company_categories"])
print(all_cleaned_jobs[0]["company_industries"])


