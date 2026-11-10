# Landly

Landly pulls UK tech SDR/BDR job openings from a jobs API, filters out non-SDR roles, non-tech companies and recruitment agencies, removes duplicates, stores the results in a database, and shows them on a filterable web page.

## Problem (Landly v1)
Instead of manually searching different job boards for jobs that match what I want, Landly pulls them all into one place.

## v1 scope
- Pull UK SDR/BDR roles from the last 30 days
- Newest at the top
- Filters: city, date posted (today, since yesterday, 7 days, 14 days, 30 days)
- Tech companies only
- Exclude recruitment agencies

## Out of scope for v1 (Phase 2+)
- Decision-maker enrichment (on-demand button)
- AI company summaries
- AI outreach: LinkedIn note, cold email and cold call script using my frameworks and CV
- RepVue and Glassdoor research links
- Keyword filter
- Daily email of new jobs
- Filters for salary, company size, stage, industry

## Tech stack
| Layer | Tool |
|---|---|
| Language | Python |
| Data source | Jobo ATS Jobs DB via RapidAPI |
| HTTP | `requests` |
| Secrets | `.env` + `python-dotenv` |
| Database | SQLite (`sqlite3`) |
| Web app | FastAPI + Uvicorn |
| Pages | Jinja2 templates, HTML/CSS |

## Project structure

Landly/
├── fetch_jobs.py # Calls the API (both searches, all pages), caches to jobs_all.json
├── load_jobs.py # Pipeline: load → clean → filter → dedupe → save to landly.db
├── main.py # FastAPI web app: serves the jobs page with filters
├── templates/
│ └── jobs.html # Jobs page (Jinja2 template)
├── static/
│ └── style.css # Page styling
├── .env # API key (not committed)
└── README.md


## How to run
1. Activate the virtual environment: `source .venv/bin/activate`
2. Add your RapidAPI key to `.env`: `RAPIDAPI_KEY=your_key`
3. **Update the jobs:** in `load_jobs.py`, set `FETCH_FROM_API`:
   - `True`: fetch fresh jobs from the API (about 3 requests) and cache them in `jobs_all.json`
   - `False`: use the cached `jobs_all.json` (no requests, for testing)

   Then run `python3 load_jobs.py`
4. **Start the web app:** `uvicorn main:app --reload`
5. Open `http://localhost:8000/jobs`

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
| company_website | `company.website` | Used for duplicate detection and the "Company site" button |
| company_categories | `company.categories` | Used by the tech filter |
| company_industries | `company.industries` | Used by the tech filter |
| occupation_id | `occupation.id` | Used by the SDR filter |
| locations | `locations` | Full list (a job can have several) |
| place | worked out | First location's city → country → "Unknown" |
| description | `description` | Used by the agency filter |
| date_posted | `date_posted` | ISO format, so it sorts correctly |
| source | `source` | Which ATS |
| link | `listing_url` | Job description page |
| first_seen | set by Landly | Date Landly first saw the job |
| last_seen | set by Landly | Date Landly last saw the job |
| rejection_reason | set by Landly | Rejected jobs only: "not sdr", "not tech", "agency" or "duplicate" |

## Rules
- **SDR/BDR filter:** keep if `occupation_id == "jobo:sales-development-representative"` **or** (the title contains "sales development representative" or "business development representative" **and** doesn't contain "manager"). The title fallback catches roles Jobo mislabels (e.g. Epicor, Carwow). The manager check keeps out roles like "SDR Manager".
- **Tech filter:** keep if the company is on the `always_keep` list, **or** categories contain `saas`, **or** industries include Software, Custom Software & IT Services, Security Products & Services, or Credit Cards & Transaction Processing. "Research & Development" is excluded on purpose, as Jobo tags non-tech companies with it.
- **always_keep:** Multiplier, SentinelOne, Carwow, Searchable, Deliveroo. Tech companies whose Jobo data is missing or incomplete.
- **Agency filter:** reject if the company name is on a blocklist (Lifelancer, ManpowerGroup Talent Solutions, Excelerate360, Huzzle) **or** the description contains a precise phrase ("curated by", "on behalf of our client"). "our client" and the HR & Staffing industry were rejected as rules because they also matched real tech companies.
- **Duplicates (within one run):** a composite dedupe key of cleaned company domain + lowercased title + place. The first job with each key is kept, and later copies are rejected. Domain beats company name: it catches "First Mile" vs "First Mile | Certified B Corp". The same title in a different city counts as a separate job. Companies with no website fall back to the company name.
- **Duplicates (across runs):** the database blocks repeats by `source_job_id`. An upsert updates `last_seen` for jobs it already has, and leaves `first_seen` unchanged.
- **Location:** a job with London AND Lisbon is included

## Flow
1. **Fetch:** call the API for both searches, all pages, and cache to `jobs_all.json`
2. **Transform:** convert each job from Jobo's format into my data model
3. **Filter:** SDR → tech → agency → duplicates. Each step only checks the jobs that passed the one before. Rejected jobs are tagged with a `rejection_reason` and saved to `rejected_jobs.json`.
4. **Save:** upsert into SQLite (`landly.db`)
5. **Display:** FastAPI reads `landly.db` and fills the `jobs.html` template, newest first
   - Filters come from the URL, e.g. `/jobs?city=London&days=7`
   - The SQL `WHERE` clause is built only from the filters chosen, using `?` placeholders

## Functions
| Function | File | Goes in | Comes out |
|---|---|---|---|
| `fetch_all_pages` | fetch_jobs.py | search term | all jobs from every page |
| `fetch_and_save` | fetch_jobs.py | (nothing) | runs both searches, saves `jobs_all.json` |
| `load_jobs` | load_jobs.py | file name | list of raw jobs |
| `clean_jobs` | load_jobs.py | raw jobs | clean jobs |
| `keep_only_sdrs` | load_jobs.py | clean jobs | SDR jobs, rejected |
| `keep_tech_jobs` | load_jobs.py | SDR jobs | tech jobs, rejected |
| `remove_agencies` | load_jobs.py | tech jobs | rejected, non-agency jobs |
| `remove_duplicates` | load_jobs.py | non-agency jobs | rejected, unique jobs |
| `save_jobs` | load_jobs.py | jobs, file name | (writes a JSON file) |
| `create_database` | load_jobs.py | (nothing) | creates the jobs table |
| `save_to_database` | load_jobs.py | jobs | (upserts into SQLite) |
| `count_jobs_in_database` | load_jobs.py | (nothing) | number of rows |
| `get_jobs` | main.py | city, days | matching jobs, newest first |
| `show_jobs` | main.py | request, city, days (from the URL) | the filled-in jobs page |

## Results (live run, 9 Nov 2026)
202 fetched → 201 (SDR) → 175 (tech) → 173 (agency) → 159 (unique). 43 rejected. 159 jobs in the database.

## Progress
- [x] Fetch from the API (both searches, all pages, cached)
- [x] Transform
- [x] Filters: SDR (with title fallback), tech (with always_keep), agency
- [x] Duplicates (within a run and across runs)
- [x] Save rejected jobs with reasons
- [x] Save to database (SQLite, with upsert)
- [x] Refactor into functions
- [x] One command runs the whole pipeline
- [x] Display: FastAPI web app with styled job cards
- [x] Filters on the page: city and date posted
- [ ] Run daily on a schedule
- [ ] Phase 2: research links, AI summaries, AI outreach, decision-maker enrichment

## Known gaps
- Jobs whose only locations are outside the UK (e.g. EvenUp, US) aren't filtered out yet. Fix: keep a job only if at least one location has `country == "United Kingdom"`.
- Jobo's company data is sometimes missing or incomplete, so the tech filter needs a manual `always_keep` list
- Jobo occasionally mislabels SDR roles with other occupation IDs (handled by the title fallback)
- `posted_after` in `fetch_jobs.py` is a fixed date. It should be worked out as "30 days ago" each run.
- The API's `total` for the BDR search may be capped at 100. Not yet confirmed.
