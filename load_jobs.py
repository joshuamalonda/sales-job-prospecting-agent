import json

# job_file is the opened file. Its contents are JSON text, and json.load turns that into Python dicts and lists
with open("jobs_page1.json") as job_file:
    job_data = json.load(job_file)

print(job_data.keys())

# start at job_data then open the jobs list, take the 1st item and gets its title
print(job_data["jobs"][0]["title"])

all_cleaned_jobs = []

# For loop that prints all the jobs with the job title, company name, and place (if there isn't a city then replace it with country)
# Then we transform the data into our clean dictionary, then add all the cleaned jobs to a list
for job in job_data["jobs"]:
    place = job["locations"][0]["city"]
    if place is None:
        place = job["locations"][0]["country"]
    clean_job = {
       "title": job["title"],
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
print(all_cleaned_jobs[0])



