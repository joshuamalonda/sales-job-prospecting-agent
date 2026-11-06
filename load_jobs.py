import json

# job_file is the opened file. Its contents are JSON text, and json.load turns that into Python dicts and lists
with open("jobs_page1.json") as job_file:
    job_data = json.load(job_file)

print(job_data.keys())

# start at job_data then open the jobs list, take the 1st item and gets its title
print(job_data["jobs"][0]["title"])

# For loop that prints all the jobs with the job title, company name, and city
for job in job_data["jobs"]:
    place = job["locations"][0]["city"]
    if place is None:
        place = job["locations"][0]["country"]
    print(job["title"], job["company"]["name"], place)





