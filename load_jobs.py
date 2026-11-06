import json

# job_file is the opened file. Its contents are JSON text, and json.load turns that into Python dicts and lists
with open("jobs_page1.json") as job_file:
    job_data = json.load(job_file)

# A list that will store all of the job data we will transform into our own data model using a dictionary
all_cleaned_jobs = []

# For loop that transforms the data into our clean dictionary, then adds all the cleaned jobs to the cleaned jobs list above
for job in job_data["jobs"]:
    # Use the city for display. If there's no city (e.g. "Remote UK"), fall back to the country
    place = job["locations"][0]["city"]
    if place is None:
        place = job["locations"][0]["country"]
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
       "link" : job["listing_url"]
}
    all_cleaned_jobs.append(clean_job)

print(len(all_cleaned_jobs))



