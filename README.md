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
| company_website | `company.website` | |
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

## Rules
- **SDR/BDR filter:** keep if `occupation_id == "jobo:sales-development-representative"`. Jobo uses this ID for SDR and BDR titles. Catches non-SDR roles the title search lets through (e.g. SDR Manager). Known exception: Epicor's BDR role has a different ID.
- **Tech filter:** keep if categories contain `saas` **or** industries include Software, Custom Software & IT Services, Security Products & Services, or Credit Cards & Transaction Processing. `saas` alone missed Snowflake, Rubrik and Teya. "Research & Development" is excluded on purpose, as Jobo tags non-tech companies with it (e.g. First Mile). Known gap: SentinelOne has no categories or industries.
- **Agency filter:** reject if the company name is on a blocklist (Lifelancer, ManpowerGroup Talent Solutions, Excelerate360, Huzzle) **or** the description contains a precise phrase ("curated by", "on behalf of our client"). "our client" and the HR & Staffing industry were rejected as rules because they also matched real tech companies.
- **Location:** a job with London AND Lisbon is included
- **What counts as "new":** date posted. To review: reposted jobs (e.g. EngageTech created in May, reposted in November) and jobs Jobo indexes late. `first_seen` may be better for "new since my last run".
- **Duplicates:** to decide. Company names and IDs differ (e.g. Snowflake twice, Cision/Brandwatch). Idea: clean the website URL and match on that plus title plus location.

## Flow
1. **Fetch:** get jobs from the API (both searches, all pages)
2. **Transform:** convert each job from Jobo's format into my data model. Keep only the fields I need, clean them up (e.g. website URLs), and store missing fields as empty.
3. **Filter:** apply the rules in order: SDR → tech → agency. Each filter only checks the jobs that passed the one before. Rejected jobs are kept in a separate list (planned: save them to a file with the reason).
4. **Save:** add new jobs to the database. For jobs already saved, update `last_seen`. The database blocks duplicates by `source_job_id`.
5. **Display:** show them, newest first

## Progress
- [x] Fetch (manual, saved to JSON for now)
- [x] Transform
- [x] Filter: page 1 test goes 100 → 99 (SDR) → 87 (tech) → 86 (agency)
- [ ] Save rejected jobs with reasons
- [ ] Duplicates
- [ ] Save to database
- [ ] Display

