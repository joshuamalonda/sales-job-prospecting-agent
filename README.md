# Landly

## Problem (Landly V1)
Instead of me manually going out and finding jobs that match what I want using different job boards, Landly pulls all of the jobs I want in one place

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
- Rejected: LinkedIn and Indeed (scraping against terms), Google jobs (no API), Adzuna/Reed (commercial-use limits; may revisit)

## Data model (one job)
- source job ID
- title
- company name
- company website
- locations (a list; a job can have several)
- description
- date posted
- first seen date
- source (which ATS)
- link to job post
- last_seen

## Rules
- SDR/BDR filter: `occupation.id == "jobo:sales-development-representative"` or `occupation.id == "jobo:business-development-representative"` 
- Tech filter: saas, tech, technology, 
- Agency filter: agency, no saas category, on behalf of our client, our client,
- Location: a job post London AND Lisbon: included
- What counts as "new": date posted
- Duplicates: company names and IDs differ, e.g. Snowflake twice, Cision/Brandwatch. Clean the website URL and match on that plus title plus location?

## Flow
<!-- The steps from "fetch jobs" to "show today's new roles". -->
1. Fetch: get jobs from the API (both searches, all pages)
2. Transform: convert each job from Jobo’s format into my data model. Keep only the fields I need, clean them up (e.g. website URLs), and store missing fields as empty.
3. Filter: apply the SDR, tech and agency rules. Keep the jobs that pass. Save the rejected ones to a separate file with the reason.
4. Save: add new jobs to the database. For jobs already saved, update last_seen. The database blocks duplicates by source job ID.
5. Display: show them, newest first

