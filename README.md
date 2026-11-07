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

## Data source
- Jobo ATS Jobs DB via RapidAPI (free plan)
  - Limits: 5,000 jobs/month, 1,000 requests/month, 10 requests/hour
  - Pulls from company career sites (Greenhouse, Lever, Ashby, Workday...), so fewer agency posts and full descriptions
- Two searches, because they return different jobs (0 overlap in testing):
  - `q="Sales Development Representative"`
  - `q="Business Development Representative"`
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
| rejection_reason | set by Landly | Rejected jobs only: "not SDR", "not tech", "agency" or "duplicate" |

## Rules
- **SDR/BDR filter:** keep if `occupation_id == "jobo:sales-development-representative"`. Jobo uses this ID for SDR and BDR titles. Catches non-SDR roles the title search lets through (e.g. SDR Manager). Known exception: Epicor's BDR role has a different ID.
- **Tech filter:** keep if categories contain `saas` **or** industries include Software, Custom Software & IT Services, Security Products & Services, or Credit Cards & Transaction Processing. `saas` alone missed Snowflake, Rubrik and Teya. "Research & Development" is excluded on purpose, as Jobo tags non-tech companies with it (e.g. First Mile). Known gap: SentinelOne has no categories or industries.
- **Agency filter:** reject if the company name is on a blocklist (Lifelancer, ManpowerGroup Talent Solutions, Excelerate360, Huzzle) **or** the description contains a precise phrase ("curated by", "on behalf of our client"). "our client" and the HR & Staffing industry were rejected as rules because they also matched real tech companies.
- **Duplicates (within one run):** a composite dedupe key of cleaned company domain + lowercased title + place. The first job with each key is kept, and later copies are rejected. Domain beats company name: it catches "First Mile" vs "First Mile | Certified B Corp". The same title in a different city counts as a separate job (e.g. Columbus Nottingham vs Manchester). Companies with no website fall back to the company name.
- **Duplicates (across runs):** the database blocks a job it already has, by `source_job_id`
- **Location:** a job with London AND Lisbon is included
- **What counts as "new":** date posted. To review: reposted jobs (e.g. EngageTech created in May, reposted in November) and jobs Jobo indexes late. `first_seen` may be better for "new since my last run".

## Flow
1. **Fetch:** get jobs from the API (both searches, all pages)
2. **Transform:** convert each job from Jobo's format into my data model. Keep only the fields I need, clean them up, and store missing fields as empty.
3. **Filter:** apply the rules in order: SDR → tech → agency → duplicates. Each step only checks the jobs that passed the one before. Rejected jobs are tagged with a `rejection_reason` and saved to `rejected_jobs.json`.
4. **Save:** add new jobs to the database. For jobs already saved, update `last_seen`. The database blocks duplicates by `source_job_id`.
5. **Display:** show them, newest first

## Functions
| Function | Goes in | Comes out |
|---|---|---|
| `load_jobs` | file name | list of raw jobs |
| `clean_jobs` | raw jobs | clean jobs |
| `keep_only_sdrs` | clean jobs | SDR jobs, rejected |
| `keep_tech_jobs` | SDR jobs | tech jobs, rejected |
| `remove_agencies` | tech jobs | non-agency jobs, rejected |
| `remove_duplicates` | non-agency jobs | unique jobs, rejected |
| `save_jobs` | a list of jobs, file name | (writes a JSON file) |


## Progress
- [x] Fetch (manual, saved to JSON for now)
- [x] Transform
- [x] Filter: page 1 test goes 100 → 99 (SDR) → 87 (tech) → 86 (agency) → 80 (duplicates)
- [x] Save rejected jobs with reasons (20 rejected: 1 not SDR, 12 not tech, 1 agency, 6 duplicates)
- [x] Refactor into functions
- [ ] Save to database (SQLite)
- [ ] Automate fetch (API call, both searches, all pages)
- [ ] Display

