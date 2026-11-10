# Landly

## Problem (Landly v1)
Instead of manually searching different job boards for jobs that match what I want, Landly pulls them all into one place.

## v1 scope (building now)
- Pull UK SDR/BDR roles from the last 30 days
- Refresh daily, newest at the top
- Filters: location (city), date posted (today, yesterday, 7 days, 14 days, 30 days), keyword (title or description)
- Tech companies only
- Exclude recruitment agencies

## Out of scope for v1 (later phases)
- Apollo link / decision makers
- Company brief (what they sell, who to, news)
- Cold call, email and LinkedIn scripts using my CV
- Sales plan
- Daily email of new jobs
- Filters for salary, company size, stage, industry

## How to run
1. Add your RapidAPI key to a `.env` file: `RAPIDAPI_KEY=your_key`
2. In `load_jobs.py`, set `FETCH_FROM_API`:
   - `True`: fetch fresh jobs from the API (about 3 requests) and cache them in `jobs_all.json`
   - `False`: use the cached `jobs_all.json` (no requests, for testing)
3. Run `python3 load_jobs.py`

## Data source
- Jobo ATS Jobs DB via RapidAPI (free plan)
  - Limits: 5,000 jobs/month, 1,000 requests/month, 10 requests/hour
  - Pulls from company career sites (Greenhouse, Lever, Ashby, Workday...), so fewer agency posts and full descriptions
- Two searches, because they return different jobs:
  - `q="Sales Development Representative"`
  - `q="Business Development Representative"`
- Fetches every page of results (`total_pages`), 100 jobs per page
- Responses are cached to `jobs_all.json` to stay within the rate limit while developing
- Rejected: LinkedIn and Indeed (scraping against terms), Google jobs (no API), Adzuna/Reed (commercial-use limits; may revisit)

## Data model (one job)
| Field | Jobo key | Notes |
|---|---|---|
| source_job_id | `id` | Jobo's ID, unique across all jobs (not `external_id`, which can clash between companies) |
| title | `title` | |
| company_name | `company.name` | |
| company_website | `company.website` | Also used for duplicate detection |
| company_categories | `company.categories` | Used by the tech filter |
| company_industries | `company.industries` | Used by the tech filter |
| occupation_id | `occupation.id` | Used by the SDR filter |
| locations | `locations` | Full list (a job can have several) |
| place | worked out | First location's city → country → "Unknown" |
| description | `description` | Used by the agency filter |
| date_posted | `date_posted` | |
| source | `source` | Which ATS |
| link | `listing_url` | Job description page |
| first_seen | set by Landly | Date Landly first saw the job |
| last_seen | set by Landly | Date Landly last saw the job |
| rejection_reason | set by Landly | Rejected jobs only: "not sdr", "not tech", "is an agency" or "duplicate" |

## Rules
- **SDR/BDR filter:** keep if `occupation_id == "jobo:sales-development-representative"` **or** (the title contains "sales development representative" or "business development representative" **and** doesn't contain "manager"). The title fallback catches roles Jobo mislabels (e.g. Epicor, Carwow). The manager check keeps out roles like "SDR Manager".
- **Tech filter:** keep if the company is on the `always_keep` list, **or** categories contain `saas`, **or** industries include Software, Custom Software & IT Services, Security Products & Services, or Credit Cards & Transaction Processing. "Research & Development" is excluded on purpose, as Jobo tags non-tech companies with it (e.g. First Mile).
- **always_keep:** Multiplier, SentinelOne, Carwow, Deliveroo, Searchable. Tech companies whose Jobo data is missing or incomplete.
- **Agency filter:** reject if the company name is on a blocklist (Lifelancer, ManpowerGroup Talent Solutions, Excelerate360, Huzzle) **or** the description contains a precise phrase ("curated by", "on behalf of our client"). "our client" and the HR & Staffing industry were rejected as rules because they also matched real tech companies.
- **Duplicates (within one run):** a composite dedupe key of cleaned company domain + lowercased title + place. The first job with each key is kept, and later copies are rejected. Domain beats company name: it catches "First Mile" vs "First Mile | Certified B Corp". The same title in a different city counts as a separate job. Companies with no website fall back to the company name.
- **Duplicates (across runs):** the database blocks repeats by `source_job_id`. An upsert updates `last_seen` for jobs it already has, and leaves `first_seen` unchanged.
- **Location:** a job with London AND Lisbon is included
- **What counts as "new":** date posted. To review: reposted jobs (e.g. EngageTech created in May, reposted in November) and jobs Jobo indexes late. `first_seen` may be better for "new since my last run".

## Flow
1. **Fetch:** call the API for both searches, all pages, and cache to `jobs_all.json`
2. **Transform:** convert each job from Jobo's format into my data model
3. **Filter:** SDR → tech → agency → duplicates. Each step only checks the jobs that passed the one before. Rejected jobs are tagged with a `rejection_reason` and saved to `rejected_jobs.json`.
4. **Save:** upsert into SQLite (`landly.db`). New jobs are inserted, and existing jobs get `last_seen` updated.
5. **Display:** show them, newest first

## Functions
| Function | File | Goes in | Comes out |
|---|---|---|---|
| `fetch_all_pages` | fetch_jobs.py | search term | all jobs from every page |
| `fetch_and_save` | fetch_jobs.py | (nothing) | runs both searches, saves `jobs_all.json` |
| `load_jobs` | load_jobs.py | file name | list of raw jobs |
| `clean_jobs` | load_jobs.py | raw jobs | clean jobs |
| `keep_only_sdrs` | load_jobs.py | clean jobs | SDR jobs, rejected |
| `keep_tech_jobs` | load_jobs.py | SDR jobs | tech jobs, rejected |
| `remove_agencies` | load_jobs.py | tech jobs | non-agency jobs, rejected |
| `remove_duplicates` | load_jobs.py | non-agency jobs | unique jobs, rejected |
| `save_jobs` | load_jobs.py | jobs, file name | (writes a JSON file) |
| `create_database` | load_jobs.py | (nothing) | creates the jobs table |
| `save_to_database` | load_jobs.py | jobs | (upserts into SQLite) |
| `count_jobs_in_database` | load_jobs.py | (nothing) | number of rows |

## Results (live run, 9 Nov 2026)
202 fetched → 201 (SDR) → 175 (tech) → 173 (agency) → 159 (unique). 43 rejected. 165 jobs in the database.

## Progress
- [x] Fetch from the API (both searches, all pages, cached)
- [x] Transform
- [x] Filters: SDR (with title fallback), tech (with always_keep), agency
- [x] Duplicates (within a run and across runs)
- [x] Save rejected jobs with reasons
- [x] Save to database (SQLite, with upsert)
- [x] Refactor into functions
- [x] One command runs the whole pipeline
- [ ] Display (FastAPI + HTML/CSS)
- [ ] Run daily on a schedule

## Known gaps
- Jobo's company data is sometimes missing or incomplete, so the tech filter needs a manual `always_keep` list
- Jobo occasionally mislabels SDR roles with other occupation IDs (handled by the title fallback)
- The API's `total` for the BDR search may be capped at 100. Not yet confirmed.