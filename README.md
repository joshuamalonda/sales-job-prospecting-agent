# Landly

A job search tool for people breaking into UK tech sales (SDR/BDR roles).

Most candidates send a CV. Landly helps you show up having **already done the job**: for any role, it builds a sourced prospecting plan for that company. It covers who they sell to, the triggers to watch for, 1–3 real accounts with evidence, the person to contact, a cold email and a cold call script, ready to send to the hiring manager as a PDF.

---

## What it does

| Feature | How |
|---|---|
| **Job feed** | Pulls UK SDR/BDR jobs from a jobs API, filters out irrelevant roles, and stores them in SQLite |
| **Filters** | By city, by date posted, and by applied / not applied |
| **Company summary** | A plain-English brief of what the company does, who they sell to and the problem they solve (OpenAI), cached per company |
| **Decision makers** | Senior sales leaders at the company (Blitz API), with a UK → Europe → US fallback |
| **Prospecting plan** | ICP, triggers, 1–3 evidence-backed target accounts, a buyer, a cold email and a cold call script, exported as a PDF |
| **Applied tracking** | Mark companies as applied; badge and filter on the job list |
| **Editable plans** | Edit the plan in the browser and save it before exporting |

---

## How the prospecting plan works

```
Job + company website
   │
   ▼
1. Get text      website → (blocked?) Exa's copy of the site → job ad
2. Build ICP     OpenAI works out the SDR's motion (who they contact, what they ask),
                 then the problem, triggers, buyer titles and search queries
3. Find accounts Exa company search → exclude the employer + companies named in the job ad
4. Find proof    Exa news from the last 90 days for each candidate
5. Rank          OpenAI picks up to 3 → code verifies every claim → AI judge checks the opening line
6. Find a buyer  Blitz: exact titles → broader titles → founders (optional)
7. Write         OpenAI writes the email + call script for the strongest account → code enforces the rules
8. Cache         Saved as JSON in SQLite: built once, loads instantly after
```

---

## Key design decisions

**Ask the AI, then verify in code.** The model has to quote 5–20 words *exactly* from its source, and the code checks that the quote really appears in that account's own evidence. This came from a real bug: the model claimed a company had raised funding when the source said nothing of the sort.

**Quality over quantity.** Accounts must score 4/5 or higher, pass the evidence checks and avoid banned phrases. One strong account beats five weak ones, and "no accounts this week" is an acceptable answer.

**Build the ICP from the SDR's motion, not "what they sell".** An acquirer's SDRs contact founders about selling their business; a SaaS vendor's SDRs book demos. Getting this first makes every later step correct, and it works across industries with no special cases.

**Fixed text by code, variable text by AI.** The cold call opener, greeting and sign-off are inserted by code, so they're word for word every time. The AI only writes what changes per company.

**Generate → check → retry once → give up gracefully.** Outreach that breaks the rules (subject over 4 words, more than 2 sentences per paragraph, banned phrases) is regenerated with the list of failures. If it fails again, it's left out rather than shown broken.

**Essential vs bonus steps.** Exa and OpenAI failures stop the plan. Blitz and outreach failures are logged and skipped, because a missing contact never blocks the plan.

**Cache everything that costs money.** Summaries, contacts and plans are each paid for once per company. Failed calls are never cached, so they retry next time.

**Never hold the database during an API call.** SQLite allows one writer at a time. Every slow call happens with the connection closed, which fixed a "database is locked" bug.

**Cut what doesn't work.** RepVue and exact Glassdoor-page lookups were unreliable and slow (wrong-company matches, search errors). They're replaced by an instant Glassdoor search link that never points to the wrong company.

---

## Tech stack

- **Backend:** Python, FastAPI, SQLite
- **Frontend:** Jinja templates, HTML/CSS, a little JavaScript
- **APIs:** OpenAI (gpt-4o-mini), Exa (company and news search), Blitz (contacts), a jobs API via RapidAPI

---

## Running it locally

```bash
git clone <repo-url>
cd Landly
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file (never commit it):
```
RAPIDAPI_KEY=...
OPENAPI_KEY=...
EXA_API_KEY=...
BLITZAPI_KEY=...
APP_USERNAME=...              # login for the whole site (the app won't start without both)
APP_PASSWORD=...
# Optional: DATABASE_PATH (default landly.db), MAX_PLANS_PER_DAY (default 10),
# MAX_CONTACT_LOOKUPS_PER_DAY (default 20), ENABLE_SCHEDULER=true (daily job refresh inside the app)
```

```bash
FETCH_FROM_API=true python3 load_jobs.py   # fetch + store jobs (without the flag: reload the cached jobs_all.json)
uvicorn main:app --reload     # open http://127.0.0.1:8000/jobs
```

**Cost per new prospecting plan:** about $0.20 of Exa, a fraction of a penny of OpenAI, and up to 6 Blitz records. Cached plans are free.

---

## Regression tests

```bash
python tests/check_plans.py                   # free: replays saved real inputs, checks every rule
python tests/check_plans.py --refresh-openai  # ~1p per company: only after a prompt change
python tests/check_plans.py --record Vertice  # paid (~$0.20 Exa): record fresh real inputs
```

`tests/golden_plans/` holds the saved inputs for Triple Whale, Vertice, PlainID and Everfield (website text, job ad, Exa results, OpenAI answers) plus hand-written expectations: vendors and competitors that must never be accounts, business-model words the ICP must use, and claim-checker cases built from real false claims. Run it after every change.

## Known limitations

- **Works best for companies with a focused ICP.** Businesses with a specific
  customer (e.g. a DTC ecommerce brand, a bank, an HR team) produce strong,
  relevant accounts. Broad, horizontal products that sell to companies of every
  size (developer infrastructure, general platforms like Redis or GitLab) often
  return few or no accounts, because the candidate pool is noisy and the tool
  deliberately drops anything it can't verify.

- **Truth over volume.** Every trigger is checked against its source, and
  anything unverified is dropped. This means some plans return 1 account, or
  none. That is by design — one account backed by real, recent evidence is more
  useful than three with weak or invented claims.

- **Always verify before sending.** Contact data comes from a third-party
  provider and can be out of date, so the suggested person should be checked on
  LinkedIn. Generated emails and call scripts are a strong first draft, not a
  finished message.

- **Built for people who already understand outbound.** Landly assumes the user
  knows what a prospecting plan is and why they'd send one to a hiring manager.
  People entirely new to sales may need that context explained first.

- **Not multi-user yet.** Saved data (applied status, plan edits) is shared, not
  per-user. Real authentication and per-user data are planned before any public
  launch.

---

## How this was built

I'm currently learning Python & SQL and I broke into tech sales at 20 years old with no degree or sales job experience. I wrote the early parts myself by hand (fetching jobs, loading them into SQLite, the first summaries). For the larger features, I used Claude Code and worked as the product owner and reviewer. I decided what "good" looked like (my email and cold call frameworks, quality over quantity, dropping features that didn't work), tested the output against my sales experience, and pushed back on weak results. I've reviewed the codebase function by function so I can explain how and why it works.