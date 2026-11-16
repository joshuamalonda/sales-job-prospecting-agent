import json
import os
import re
import sqlite3
from datetime import date, timedelta

import requests
from dotenv import load_dotenv
from openai import OpenAI

from contacts import BASE_URL as BLITZ_URL
from contacts import HEADERS as BLITZ_HEADERS
from contacts import domain_to_linkedin

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAPI_KEY"))
EXA_HEADERS = {"x-api-key": os.getenv("EXA_API_KEY"), "Content-Type": "application/json"}
EXA_SEARCH_URL = "https://api.exa.ai/search"
DATABASE = "landly.db"

# Phrases that make writing sound AI-generated or like guessing. Any account whose
# why_now or opening_line contains one of these is dropped (checked in code, not just asked for).
BANNED_PHRASES = ["likely", "suggests", "indicates", "perfect opportunity", "impressive",
                  "i noticed", "i heard", "i saw", "congrat", "digital transformation",
                  "leverage", "streamline"]

# Cheap first filter for opening lines (no API call). The real judgement is done by judge_opener().
OPENER_BANNED = ["challenge", "foresee", "brand legacy", "pain point", "top of mind", "keeps you up",
                 "how are you planning", "what are your plans", "how do you plan", "your priorities"]

# Trigger types containing these aren't publicly observable events, so they're removed in code
TRIGGER_BANNED = ["digital transformation", "growth plan", "revenue target", "loan", "award", "increased",
                  "a need for", "seeking to", "looking to", "demand for", "competition", "initiative"]

# Region words that appear in SDR job titles, longest/most specific first.
REGIONS = ["North EMEA", "South EMEA", "Central EMEA", "Northern Europe", "Southern Europe",
           "Nordics", "Benelux", "DACH", "UK&I", "UKI", "Ireland", "France", "Germany", "Spain",
           "Italy", "Netherlands", "EMEA", "Europe", "North America", "APAC", "ANZ", "LATAM"]


def to_domain(website):
    """'https://www.triplewhale.com/about' -> 'triplewhale.com'"""
    domain = website.lower().split("//")[-1].split("/")[0]
    return domain.removeprefix("www.")


def territory_for(place, job_title):
    """Work out the sales territory from the job.
    'Sales Development Representative, EMEA' -> 'EMEA'
    'SDR - Nordics + Benelux'                -> 'Nordics + Benelux'
    No region in the title                   -> the job's location."""
    # Find every region named in the title, as a whole word ("EMEA" yes, "EMEAN" no)
    found = []
    for region in REGIONS:
        whole_word_pattern = rf"(?<!\w){re.escape(region)}(?!\w)"
        if re.search(whole_word_pattern, job_title or "", re.I):
            found.append(region)

    # Drop a match that sits inside a longer one, e.g. "EMEA" when "North EMEA" was found
    most_specific = []
    for match in found:
        inside_a_longer_match = False
        for other in found:
            if match != other and match.lower() in other.lower():
                inside_a_longer_match = True
        if not inside_a_longer_match:
            most_specific.append(match)

    if most_specific:
        return " + ".join(most_specific)
    if not place or place == "United Kingdom":
        return "United Kingdom"
    return f"{place} and the wider UK"                                 # a city, e.g. "London"


# Some sites (e.g. lovable.dev) return 403 to anything that doesn't look like a normal browser
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def fetch_website_text(domain):
    """Step 1a: download the homepage and strip it to plain text. Raises if the site blocks us."""
    response = requests.get(f"https://{domain}", timeout=30, headers=BROWSER_HEADERS)
    response.raise_for_status()
    html_without_code = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", response.text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html_without_code)          # remove the remaining HTML tags
    text = re.sub(r"\s+", " ", text).strip()                   # squash spaces and line breaks
    return text[:8000]


def get_job_description(company_name):
    """The company's own SDR job ad from our jobs table (the longest one, if several)."""
    connection = sqlite3.connect(DATABASE, timeout=30)          # quick read, closed before any API call
    row = connection.execute(
        "SELECT description FROM jobs WHERE company_name = ? AND description IS NOT NULL "
        "ORDER BY length(description) DESC LIMIT 1", (company_name,)).fetchone()
    connection.close()
    if not row:
        return ""
    return row[0][:6000]


def exa_site_text(domain):
    """Get a blocked site's text from Exa's index instead of the live site.
    Uses /search limited to the company's own domain (/contents isn't on our plan)."""
    payload = {
        "query": f"what {domain} does, its products and customers",
        "includeDomains": [domain],
        "numResults": 3,
        "contents": {"text": {"maxCharacters": 3000}},
    }
    response = requests.post(EXA_SEARCH_URL, headers=EXA_HEADERS, json=payload, timeout=60)
    response.raise_for_status()

    pages = []
    for result in response.json().get("results", []):
        pages.append(result.get("text") or "")
    text = re.sub(r"\s+", " ", " ".join(pages)).strip()
    return text[:8000]


def get_website_text(company_name, domain):
    """Website text: the live homepage, else Exa's copy of the site, else "" (job ad alone will be used)."""
    try:
        text = fetch_website_text(domain)
        if text:
            print(f"Website source for {company_name}: live homepage ({domain})")
            return text
    except Exception as error:
        print(f"Website fetch failed for {company_name}: {error} - trying Exa's index")
    try:
        text = exa_site_text(domain)
        if text:
            print(f"Website source for {company_name}: Exa index of {domain}")
            return text
    except Exception as error:
        print(f"Exa site search failed for {company_name}: {error}")
    print(f"Website source for {company_name}: none - using the job ad alone")
    return ""


def build_icp(company_name, website_text, job_description, territory):
    """Step 1b: work out the SDR's motion (who they contact and what they ask), then derive the ICP from it."""
    if not website_text and not job_description:
        raise ValueError(f"No website text or job description for {company_name}")
    prompt = f"""Company: {company_name}
Sales territory for this role: {territory}

JOB AD for the SDR role (best source for WHO the SDRs target: segment, region, company size, who they contact):
{job_description or "(not available)"}

WEBSITE TEXT (best source for WHAT the company offers):
{website_text or "(not available)"}

You are a sharp SDR planning prospecting for this company. Start by working out the SDR's actual motion:
who this company's SDRs reach out to, and what they ask those people to do. Companies differ:
a software vendor's SDRs book demos with buyers; an acquirer's SDRs contact founders/owners about selling
their business; a marketplace may recruit sellers or buyers; an agency or recruiter pitches clients;
an investor sources companies to invest in. Work it out from the job ad first, then the website.
Every other field must follow from "sdr_motion" - NOT from a generic idea of "what they sell".
Write plainly, like a person, not marketing copy.
Return JSON with exactly these keys:
"companies_in_job_ad": every company name mentioned in the job ad (the employer, its parent group, sister or
   portfolio companies), e.g. ["Everfield", "Depotnet"]. These are never prospects,
"sdr_motion": one sentence: who the SDRs contact (title + type of company) and what they ask them to do.
   e.g. "Contact founders of profitable vertical SaaS companies to explore selling their business",
   or "Contact Heads of Growth at DTC brands to book a demo",
"summary": one plain-English sentence on what {company_name} does and for whom,
"problem": in one sentence, the specific situation on the PROSPECT's side that makes them say yes to the
   SDR's ask (from the prospect's point of view, e.g. "A founder wants to step back or cash out but doesn't
   want a buyer who will gut the product"). Don't name {company_name},
"target_customers": a SPECIFIC description of the companies the SDRs contact: business model, size band
   (employees or revenue), ownership/stage and tech if relevant. Use the job ad's segment and region.
   Never "all sizes", "any industry", "globally" or "businesses of all kinds",
"trigger_types": 3-5 PUBLICLY OBSERVABLE events that make the prospect ready for the SDR's ask right now,
   each under 12 words. Each must be findable in a news search, press release, job board, Companies House
   filing or LinkedIn post, and connect directly to "problem". No vague states ("increased demand",
   "a need for", "increased competition"). Never generic ones: "digital transformation", "growth plans",
   "revenue targets", "secured a loan", "won an award", "raised funding" (unless funding is itself the trigger
   for this specific motion),
"buyer_titles": 3-5 titles of the people the SDRs contact, exactly as written on LinkedIn, senior enough to say yes
   to the ask (e.g. Founder, CEO, Managing Director, Head of X, VP X). Never analysts or coordinators,
"fallback_titles": 3-5 broader senior titles at the same kind of company, in case the exact ones don't exist,
"exa_queries": 3 search queries describing the companies the SDRs contact, headquartered or operating in
   {territory}, by facts (business model, size, ownership, location, technology). Never {company_name}'s
   competitors. No company names, no vague words."""
    return ask_openai_for_json(prompt)


def ask_openai_for_json(prompt):
    """Send one prompt to gpt-4o-mini and return its JSON answer as a Python dict.
    temperature=0 makes the answers as consistent as possible."""
    response = client.chat.completions.create(
        model="gpt-4o-mini", temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}])
    return json.loads(response.choices[0].message.content)


def find_candidates(queries, exclude_domain):
    """Step 2: Exa company search. Returns real companies."""
    candidates_by_url = {}                       # keyed by url, so the same company is never added twice
    for query in queries:
        payload = {
            "query": query,
            "category": "company",
            "type": "auto",
            "numResults": 10,
            "contents": {"highlights": True},
        }
        response = requests.post(EXA_SEARCH_URL, headers=EXA_HEADERS, json=payload, timeout=60)
        response.raise_for_status()

        for result in response.json().get("results", []):
            url = result.get("url", "")
            if exclude_domain in url or url in candidates_by_url:
                continue
            # Exa may attach the company's details ("entities"); use its proper name if it's there
            entities = result.get("entities") or [{}]
            properties = entities[0].get("properties") or {}
            name = properties.get("name") or result.get("title")
            candidates_by_url[url] = {"name": name, "url": url}
    return list(candidates_by_url.values())


def find_trigger_evidence(candidate, trigger_types, days=90):
    """Step 3: recent news/pages about one candidate, searching for OUR trigger types
    (not generic funding news), with real links."""
    since = (date.today() - timedelta(days=days)).isoformat()
    query = f"{candidate['name']} ({candidate['url']}) news: " + "; ".join(trigger_types)
    payload = {
        "query": query,
        "type": "auto",
        "numResults": 3,
        "startPublishedDate": since,
        "contents": {"highlights": True},
    }
    response = requests.post(EXA_SEARCH_URL, headers=EXA_HEADERS, json=payload, timeout=60)
    response.raise_for_status()

    evidence = []
    for result in response.json().get("results", []):
        published = result.get("publishedDate") or ""
        highlights = result.get("highlights") or []
        evidence.append({
            "title": result.get("title"),
            "url": result.get("url"),
            "date": published[:10],                          # "2026-11-01T00:00:00Z" -> "2026-11-01"
            "snippet": " ".join(highlights)[:400],
        })
    return evidence


def normalise(text):
    """Lowercase and squash all whitespace, so a quote still matches if the snippet has line breaks."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def parse_strength(value):
    """Turn whatever the model returned into a whole number.
    5 -> 5, 4.5 -> 4, "5" -> 5, "4/5" -> 4, "Strength: 5" -> 5. Missing or no number at all -> 0."""
    if isinstance(value, bool):                        # True/False are technically ints in Python - not valid here
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+(\.\d+)?", str(value or ""))       # the first number in the text
    if not match:
        return 0
    return int(float(match.group()))


def check_account(account, evidence_by_account):
    """Return None if the account passes every check, otherwise a short reason it failed."""
    # 1. The evidence link must belong to THIS account's own search results
    own_evidence = evidence_by_account.get(account.get("url"), {})
    snippet = own_evidence.get(account.get("evidence_url"))
    if snippet is None:
        return "evidence_url is not one of this account's own sources"

    # 2. The quote must be copied word for word from that source
    quote = normalise(account.get("evidence_quote"))
    if len(quote) < 15 or quote not in normalise(snippet):
        return "evidence_quote not found verbatim in the source"

    # 3. Strong accounts only
    strength = parse_strength(account.get("strength"))
    if strength < 4:
        return f"strength {strength} is below 4"

    # 4. No guessing words, compliments or buzzwords in why_now.
    #    (The opening line is checked separately in finalise_opener - a bad opener doesn't sink the account.)
    why_now = (account.get("why_now") or "").lower()
    banned = [phrase for phrase in BANNED_PHRASES if phrase in why_now]
    if banned:
        return f"why_now uses banned phrase(s): {', '.join(banned)}"
    return None


def opener_precheck(opener):
    """Cheap first filter, no API call. Returns a reason it fails, or None."""
    if opener.count("?") != 1:
        return "must ask exactly one question"
    found = [phrase for phrase in BANNED_PHRASES + OPENER_BANNED if phrase in opener.lower()]
    if found:
        return f"banned phrase(s): {', '.join(found)}"
    return None


def judge_opener(account, icp, opener):
    """Second gpt-4o-mini call: a strict reviewer judges the opening line (and why_now).
    Returns {"pass": bool, "reason": str, "rewrite": str}."""
    prompt = f"""You review cold-call opening lines written by an SDR. Be strict.
SDR motion (who we contact and what we ask): {icp.get('sdr_motion', '')}
Trigger: {account.get('trigger', '')}
Evidence quote: "{account.get('evidence_quote', '')}"
Why now: {account.get('why_now', '')}
Opening line: "{opener}"

PASS only if ALL of these are true:
1. The opening line references the specific fact (the actual name, place, product, deal, hire or number).
2. It asks ONE concrete question a busy buyer could answer in a sentence from their own situation -
   not something they could brush off with a generic line.
3. No generic phrasing: "how will this impact", "moving forward", "challenges", "foresee", "navigate",
   "going forward", "what are your thoughts", "in today's".
4. It sounds like a real person talking, not a template.
5. "Why now" only states what the evidence supports (fail it for invented facts, not for style).
Return JSON: {{"pass": true or false, "reason": "one short sentence", "rewrite": "a better opening line that
would pass: the fact, then one specific question leading towards the SDR motion, using only facts in the
evidence quote. Empty string if pass is true."}}"""
    verdict = ask_openai_for_json(prompt)
    return {
        "pass": verdict.get("pass") is True,                  # only a real true counts, not "yes"
        "reason": str(verdict.get("reason") or ""),
        "rewrite": str(verdict.get("rewrite") or "").strip(),
    }


def finalise_opener(account, icp):
    """Judge the opening line; if it fails, try the judge's rewrite once.
    If that fails too, keep the account but remove the opening line (the account is still useful)."""
    opener = (account.get("opening_line") or "").strip()
    account["opener_review"] = []                          # judge reasons, kept for debugging
    for attempt in ("original", "rewrite"):
        verdict = judge_opener(account, icp, opener)
        precheck = opener_precheck(opener)
        passed = verdict["pass"] and precheck is None

        reason = verdict["reason"]
        if precheck:
            reason += f" [precheck: {precheck}]"
        result_label = "PASS" if passed else "FAIL"
        account["opener_review"].append(f"{attempt}: {result_label} - {reason}")
        print(f"  Judge ({account.get('name')}, {attempt}): {result_label} - {reason}")

        if passed:
            account["opening_line"] = opener
            return
        opener = verdict["rewrite"]
        if attempt == "original" and opener:
            print(f"    Trying rewrite: {opener}")
        if not opener:
            break
    account["opening_line"] = None


def rank_accounts(icp, candidates, top_n=3):
    """Step 4: up to 3 STRONG accounts, each claim backed by an exact quote from real evidence."""
    # Nothing to judge without evidence
    candidates = [candidate for candidate in candidates if candidate["evidence"]]
    if not candidates:
        return []

    prompt = f"""You are a sharp SDR. What our company does: {icp['summary']}
Our SDR motion (who we contact and what we ask): {icp.get('sdr_motion', '')}
The prospect's situation that makes them say yes: {icp.get('problem', '')}
Target accounts: {icp['target_customers']}
Triggers we look for: {icp['trigger_types']}
Buyer titles: {icp['buyer_titles']}

Candidate accounts, each with recent evidence (title, url, date, snippet):
{json.dumps(candidates, indent=1)}

Pick UP TO {top_n} accounts - only genuinely strong ones. Returning 1 is better than including a weak one.
Returning none is fine.
Rules:
- Only pick accounts that match our target accounts and SDR motion. Never pick our direct competitors.
- The evidence must clearly be about THIS company (at its url), not a similarly named one. If in doubt, skip it.
- The evidence must show one of OUR trigger types happening recently. Revenue targets, loans, generic funding,
  awards and generic company news do NOT count.
- Evidence may be in any language. Copy "evidence_quote" in its original language, but write everything else in English.
- "url" = the account's url exactly as given above.
- "trigger" = the actual event in a few words, with when it happened (e.g. "hired a VP Marketing in October").
- "evidence_url" = the url of the evidence item that proves it.
- "evidence_quote" = 5-20 words copied EXACTLY, character for character, from that evidence's snippet, proving the trigger.
- "why_now" = two short sentences. First: the fact, plainly. Second: in your own words, what that fact means
  for THIS account's version of the problem (e.g. "Every new market adds ad channels to compare.").
  Don't repeat the problem sentence above, don't name our company. State it as fact - no guessing words.
- "persona" = copy exactly one title from our buyer titles - the one I'd approach first. Never the role being hired.
- "opening_line" = what I'd actually say to that person, leading towards our SDR motion: one sentence stating the
  fact, then ONE question. Exactly one question mark. Sound like a person, short and direct.
  The question must name something specific from the trigger (the place, product, hire, deal or number) and ask
  about a concrete consequence of it - something only this account could answer, never a question the prospect
  could brush off with a generic line. Bad: "What challenges do you foresee with this expansion?"
  Good: "Is the Newcastle sales team selling the same product as London, or a cut-down version for smaller firms?"
  Never start with "I noticed", "I heard" or "I saw". No compliments, no "congrats", no buzzwords.
- Never use these words anywhere in why_now or opening_line: {', '.join(BANNED_PHRASES)}.
- Never use these in opening_line: {', '.join(OPENER_BANNED)}.
- "strength" = REQUIRED on every account: a JSON integer from 1 to 5, not a string
  (5 = clear fit + fresh, specific trigger directly tied to the problem; 4 = good; 3 or below = weak).
Use ONLY the evidence given. Never invent facts.
Return JSON in exactly this shape (values are examples):
{{"accounts": [{{"name": "Acme Ltd", "url": "https://acme.com/", "trigger": "opened a Berlin office in October",
  "evidence_url": "https://news.example.com/acme-berlin", "evidence_quote": "Acme has opened its first office in Berlin",
  "why_now": "...", "persona": "...", "opening_line": "...", "strength": 4}}]}}"""
    accounts = ask_openai_for_json(prompt).get("accounts", [])

    # evidence_by_account = {account url: {evidence url: snippet}}
    #   - lets us check each account only against its OWN sources
    # dates = {evidence url: date}
    evidence_by_account = {}
    dates = {}
    for candidate in candidates:
        snippets_by_url = {}
        for evidence in candidate["evidence"]:
            snippets_by_url[evidence["url"]] = evidence["snippet"]
            dates[evidence["url"]] = evidence["date"]
        evidence_by_account[candidate["url"]] = snippets_by_url

    verified = []
    shown_raw = False
    for account in accounts:
        problem = check_account(account, evidence_by_account)
        if problem:
            print(f"Dropped {account.get('name')}: {problem}")
            if not shown_raw:                                  # debug: show exactly what the model sent once
                print("  Raw JSON from the model:", json.dumps(account, ensure_ascii=False))
                shown_raw = True
            continue
        account["evidence_date"] = dates.get(account["evidence_url"], "")
        # The model sometimes invents a persona (e.g. the job being hired). Fall back to our top buyer title.
        if account.get("persona") not in icp["buyer_titles"]:
            account["persona"] = icp["buyer_titles"][0]
        verified.append(account)

    verified = verified[:top_n]
    for account in verified:                                   # only judge accounts we're keeping
        finalise_opener(account, icp)
    return verified


def find_buyer(account_url, buyer_titles, fallback_titles):
    """Step 5 (optional): best buyer at the account (Blitz). Exact titles -> broader -> founders."""
    company_linkedin = domain_to_linkedin(to_domain(account_url))
    if not company_linkedin:
        return None
    # Blitz tries each group of titles in order and stops at the first one that finds someone
    exact_titles = {
        "include_title": buyer_titles,
        "exclude_title": ["assistant", "intern", "analyst", "coordinator", "associate", "specialist", "executive"],
        "location": ["WORLD"],
    }
    broader_titles = {
        "include_title": fallback_titles or buyer_titles,
        "exclude_title": ["assistant", "intern", "analyst", "coordinator"],
        "location": ["WORLD"],
    }
    founders = {
        "include_title": ["Founder", "Co-founder", "CEO"],
        "exclude_title": ["assistant"],
        "location": ["WORLD"],
    }
    payload = {
        "company_linkedin_url": company_linkedin,
        "cascade": [exact_titles, broader_titles, founders],
        "max_results": 1,
    }
    response = requests.post(f"{BLITZ_URL}/v2/search/waterfall-icp-keyword",
                             headers=BLITZ_HEADERS, json=payload, timeout=60)
    response.raise_for_status()

    results = response.json().get("results", [])
    if not results:
        return None
    person = results[0]["person"]

    # Their current job title is the first entry in their work history
    title = ""
    if person.get("experiences"):
        title = person["experiences"][0]["job_title"]
    return {"name": person.get("full_name"), "title": title, "linkedin": person.get("linkedin_url")}


def clean_triggers(icp):
    """Remove trigger types that aren't publicly observable events (the prompt asks, this enforces)."""
    kept = []
    for trigger in icp.get("trigger_types", []):
        bad = [phrase for phrase in TRIGGER_BANNED if phrase in trigger.lower()]
        if bad:
            print(f"Removed trigger '{trigger}': {', '.join(bad)}")
        else:
            kept.append(trigger)
    if not kept:
        raise ValueError("No usable trigger types after filtering")
    icp["trigger_types"] = kept


def is_excluded(candidate, excluded_names):
    """True if a candidate is the hiring company or one it names in the job ad (parent, sister, portfolio)."""
    name = (candidate.get("name") or "").lower()
    url = candidate.get("url", "").lower()
    for excluded in excluded_names:
        if len(excluded) < 3:                                  # too short to match safely
            continue
        if excluded in name:                                   # "depotnet" in "depotnet ltd"
            return True
        if name and name in excluded:                          # "depotnet" in "depotnet group"
            return True
        if excluded.replace(" ", "") in url:                   # "my company" -> "mycompany" in the url
            return True
    return False


# ---------- Outreach: email + cold call script for the strongest account ----------

# Fixed text - added by code so it is always word for word, never generated
CALL_OPENER = ("Hi {name}, I'll be totally honest, this is a cold call but a well researched one. "
               "Have you got 30 seconds so I can explain why I've chosen to call you?")
CALL_GUIDANCE = ("Be curious, ask questions, look for pain, explain how {company} could help solve that pain, "
                 "ask for the meeting.")

# Marketing words that make outreach sound like a template (checked in the email and the call script)
BUZZWORDS = ["data-driven", "optimiz", "optimis", "enhanc", "insights", "solution", "empower", "seamless",
             "cutting-edge", "innovative", "game-chang", "synergy", "robust", "unlock", "drive growth"]

# The email may open with "I noticed", so that one phrase is allowed there
EMAIL_BANNED = [phrase for phrase in BANNED_PHRASES if phrase != "i noticed"] + BUZZWORDS


def pick_best_account(accounts):
    """Strongest trigger wins; on a tie, the freshest evidence date.
    ISO dates like '2026-11-09' sort correctly as text, and a missing date ('') sorts last."""
    if not accounts:
        return None

    def strength_then_date(account):
        # max() compares these pairs: strength first, then the date only if strengths are equal
        return (parse_strength(account.get("strength")), account.get("evidence_date") or "")

    return max(accounts, key=strength_then_date)


def first_name(buyer):
    """'Leah Uka' -> 'Leah'. None if Blitz didn't find anyone."""
    if buyer and (buyer.get("name") or "").strip():
        return buyer["name"].split()[0]
    return None


def count_sentences(paragraph):
    """Counts '.', '!' or '?' followed by a space or the end. '£14.3m' doesn't count (no space after the dot)."""
    return len(re.findall(r"[.!?](\s|$)", paragraph.strip())) or 1


def clean_email_body(text):
    """Keep only the body: drop any greeting or sign-off the model added anyway (code adds its own)."""
    # Paragraphs are separated by a blank line; skip empty ones
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", text or ""):
        if paragraph.strip():
            paragraphs.append(paragraph.strip())

    # A short first paragraph starting "Hi"/"Hello"/... is a greeting - remove it
    if paragraphs:
        first = paragraphs[0]
        is_greeting = re.match(r"^(hi|hello|hey|dear)\b", first, re.I) and len(first.split()) <= 4
        if is_greeting:
            paragraphs = paragraphs[1:]

    # Remove sign-offs like "Best," or "Kind regards"
    body = []
    for paragraph in paragraphs:
        if not re.match(r"^(best|thanks|cheers|regards|kind regards)\b", paragraph, re.I):
            body.append(paragraph)
    return body


def check_outreach(draft, account):
    """Return a list of rule failures (empty = all good)."""
    problems = []
    subject = (draft.get("subject") or "").strip()
    if not subject or len(subject.split()) > 4:
        problems.append("subject must be 1-4 words")

    paragraphs = clean_email_body(draft.get("email"))
    if not paragraphs or len(paragraphs) > 4:
        problems.append("email body must be 1-4 paragraphs")
    for number, paragraph in enumerate(paragraphs, 1):
        if count_sentences(paragraph) > 2:
            problems.append(f"email paragraph {number} has more than 2 sentences")
    # The first paragraph must state the observed trigger: it has to share a real word
    # (4+ letters or digits) with the trigger or the evidence quote
    if paragraphs:
        trigger_text = f"{account.get('trigger', '')} {account.get('evidence_quote', '')}".lower()
        trigger_words = set(re.findall(r"[a-z0-9]{4,}", trigger_text))
        first_paragraph_words = set(re.findall(r"[a-z0-9]{4,}", paragraphs[0].lower()))
        shared_words = trigger_words & first_paragraph_words
        if not shared_words:
            problems.append("first paragraph must mention the trigger")

    # Banned phrases: the email has its own list ("I noticed" is allowed there), the call script uses the full list
    email_text = " ".join(paragraphs).lower()
    call_text = f"{draft.get('call_reason', '')} {draft.get('call_question', '')}".lower()
    found = []
    for phrase in EMAIL_BANNED:
        if phrase in email_text:
            found.append(phrase)
    for phrase in BANNED_PHRASES + BUZZWORDS:
        if phrase in call_text:
            found.append(phrase)
    if found:
        problems.append(f"banned phrase(s): {', '.join(sorted(set(found)))}")

    if not (draft.get("call_reason") or "").strip():
        problems.append("call_reason is empty")
    question = (draft.get("call_question") or "").strip()
    if not question.lower().startswith("how are you currently") or not question.endswith("?"):
        problems.append('call_question must start "How are you currently" and end with "?"')
    return problems


def generate_outreach(company_name, icp, account, feedback=None):
    """One gpt-4o-mini call that writes the email body, subject, call reason and call question."""
    buyer = account.get("buyer")
    if buyer:
        buyer_line = f"{buyer['name']}, {buyer.get('title') or ''}"
    else:
        buyer_line = "unknown (not found)"

    # On the second attempt, tell the model exactly which rules the first draft broke
    fix = ""
    if feedback:
        fix = (f"\nYour previous draft broke these rules - fix them: {'; '.join(feedback)}. "
               "Return ALL four keys again (subject, email, call_reason, call_question).\n")

    prompt = f"""You write outreach for an SDR applying to {company_name}. The SDR is prospecting this account
on {company_name}'s behalf. Use ONLY the facts below - never invent numbers, names or events.

{company_name}'s SDR motion: {icp.get('sdr_motion', '')}
The pain {company_name} solves (prospect's point of view): {icp.get('problem', '')}
What {company_name} does: {icp.get('summary', '')}
Account: {account.get('name')}
Observed trigger: {account.get('trigger')}
Evidence quote: "{account.get('evidence_quote')}"
Why now: {account.get('why_now')}
Person: {buyer_line}
{fix}
Return JSON with exactly these keys:
"subject": 2-4 words, all lowercase, naming the concrete pain (e.g. "new store attribution", "reps chasing contact data").
   No punctuation.
"email": ONLY the body - no greeting, no sign-off. Paragraphs separated by a blank line.
   Max 4 paragraphs, max 2 sentences each, in this order:
   1. The observed trigger, stated plainly (may start "I noticed").
   2. The relevant pain and its impact, phrased as what you see teams like theirs struggle with.
   3. How {company_name} solves that pain.
   4. The call to action, as a question.
   The pain must be concrete - what actually goes wrong for this account because of the trigger
   (e.g. "not knowing which ads drove the new store's first sales"), not a vague benefit.
   No buzzwords ({', '.join(BUZZWORDS)}), no "congrats", no compliments.
   Name the trigger with the evidence quote's own words for names, places and products - never reword them.
"call_reason": 2 sentences said on a cold call: state the trigger exactly, then the issue it could create and
   the consequence. Never say "I saw", "I noticed" or "I heard" - say where you looked, e.g.
   "I was looking through your LinkedIn and saw...".
"call_question": one question starting "How are you currently" about that specific pain.

Style example email (another company, for tone only):
I noticed Bolt for Business is hiring a Lead GTM Engineer to automate manual sales tasks and improve lead data.

We speak with B2B sales teams who find that reaching the right buyers across markets can take too much research, leaving less time for conversations.

At Cognism we help sales teams get accurate contact data and automate manual sales processes to give reps more time on the phones which leads to increased pipeline.

Would it be worth exploring whether we could help your reps spend less time finding contact details and more time speaking to buyers?

Style example call_reason: "I was looking through your company's annual report and saw you estimate around £14.3m could be required to bring the portfolio to EPC B or better. When there's that level of improvement spend across multiple buildings, we often see the challenge become knowing which assets should receive investment first."
Style example call_question: "How are you currently deciding which properties should be prioritised?\""""
    draft = ask_openai_for_json(prompt)
    # Tidy the subject in code: no surrounding spaces or full stops, all lowercase
    draft["subject"] = (draft.get("subject") or "").strip().strip(".").lower()
    return draft


def write_outreach(company_name, icp, accounts):
    """Email + cold call script for the strongest account only. Regenerates once if a rule fails.
    Returns None (and nothing is shown) if it still fails."""
    account = pick_best_account(accounts)
    if not account:
        return None
    draft = generate_outreach(company_name, icp, account)
    problems = check_outreach(draft, account)
    if problems:
        print(f"Outreach draft 1 failed: {problems} - regenerating once")
        draft = generate_outreach(company_name, icp, account, feedback=problems)
        problems = check_outreach(draft, account)
        if problems:
            print(f"Outreach draft 2 failed: {problems} - no outreach saved")
            return None

    # If Blitz found no one, leave a placeholder for me to fill in by hand
    name = first_name(account.get("buyer"))
    email_name = name or "{first name}"
    call_name = name or "{Name}"

    # Greeting and sign-off are added here so they're always exactly right
    email_parts = [f"Hi {email_name}"] + clean_email_body(draft["email"]) + ["Best,\nJosh"]
    email = "\n\n".join(email_parts)                          # a blank line between each part

    return {
        "account_url": account.get("url"),
        "account_name": account.get("name"),
        "subject": draft["subject"],
        "email": email,
        "call": {
            "opener": CALL_OPENER.format(name=call_name),
            "reason": draft["call_reason"].strip(),
            "question": draft["call_question"].strip(),
            "guidance": CALL_GUIDANCE.format(company=company_name),
        },
    }


def build_pack(company_name, website, territory):
    """Run the whole pipeline for one company and return the plan as a dict."""
    domain = to_domain(website)

    # Step 1: who the SDRs target. Always give the model both: the job ad (who the SDRs target)
    # and the website (what the company offers)
    website_text = get_website_text(company_name, domain)
    job_description = get_job_description(company_name)
    icp = build_icp(company_name, website_text, job_description, territory)
    clean_triggers(icp)

    # Never prospect the employer or companies its job ad names (e.g. Everfield's portfolio company Depotnet)
    excluded = set()
    for name in [company_name] + icp.get("companies_in_job_ad", []):
        if name:
            excluded.add(name.lower().strip())

    # Step 2: find companies that match
    candidates = []
    for candidate in find_candidates(icp["exa_queries"], domain):
        if is_excluded(candidate, excluded):
            print(f"Excluded {candidate['name']}: named in the job ad")
        else:
            candidates.append(candidate)
    candidates = candidates[:15]                                       # cap at 15 to control cost

    # Step 3: recent evidence for each one
    for candidate in candidates:
        candidate["evidence"] = find_trigger_evidence(candidate, icp["trigger_types"])

    # Step 4: keep only the strong, verified accounts
    accounts = rank_accounts(icp, candidates)

    # Step 5: the person to contact at each account
    for account in accounts:
        try:
            account["buyer"] = find_buyer(account["url"], icp["buyer_titles"], icp.get("fallback_titles", []))
        except Exception as error:                                     # a contact is a bonus, never a blocker
            print(f"Buyer lookup failed for {account['name']}: {error}")
            account["buyer"] = None

    # Step 6: email + call script for the best account
    try:
        outreach = write_outreach(company_name, icp, accounts)
    except Exception as error:                                         # outreach is a bonus, never a blocker
        print(f"Outreach failed for {company_name}: {error}")
        outreach = None

    return {
        "company": company_name,
        "domain": domain,
        "territory": territory,
        "generated_at": date.today().isoformat(),
        "icp": icp,
        "accounts": accounts,
        "outreach": outreach,
    }


def create_packs_table():
    """prospect_packs = one saved plan per company (plus my hand edits, if any)."""
    connection = sqlite3.connect(DATABASE)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS prospect_packs (
            company_name TEXT UNIQUE,
            pack_json TEXT,
            created_at TEXT,
            edited_html TEXT
        )
    """)
    # Older databases were created before edited_html existed - add the column if it's missing
    columns = [row[1] for row in connection.execute("PRAGMA table_info(prospect_packs)")]
    if "edited_html" not in columns:
        connection.execute("ALTER TABLE prospect_packs ADD COLUMN edited_html TEXT")
    connection.commit()
    connection.close()


def get_edited_html(company_name):
    """The hand-edited version of the plan, or None if it hasn't been edited."""
    connection = sqlite3.connect(DATABASE, timeout=30)
    row = connection.execute(
        "SELECT edited_html FROM prospect_packs WHERE company_name = ?", (company_name,)).fetchone()
    connection.close()
    if not row:
        return None
    return row[0]


def save_edited_html(company_name, html):
    """Save my hand-edited version of a company's plan."""
    connection = sqlite3.connect(DATABASE, timeout=30)
    connection.execute(
        "UPDATE prospect_packs SET edited_html = ? WHERE company_name = ?", (html, company_name))
    connection.commit()
    connection.close()


def get_pack(company_name, website, territory, refresh=False):
    """Cache first. Build only if we don't have one (or refresh=True). Errors raise, nothing saved."""
    if not refresh:
        connection = sqlite3.connect(DATABASE, timeout=30)
        row = connection.execute(
            "SELECT pack_json FROM prospect_packs WHERE company_name = ?", (company_name,)).fetchone()
        connection.close()
        if row:
            return json.loads(row[0])

    if not website:
        raise ValueError(f"No website saved for {company_name}")
    # Slow, paid API calls happen here with NO database connection open.
    # On refresh the old plan stays saved until the new one is ready, so a failed rebuild loses nothing.
    pack = build_pack(company_name, website, territory)

    # INSERT OR REPLACE swaps in a brand-new row, so any edited_html is cleared - only once the rebuild succeeded
    connection = sqlite3.connect(DATABASE, timeout=30)
    connection.execute(
        "INSERT OR REPLACE INTO prospect_packs (company_name, pack_json, created_at) VALUES (?, ?, ?)",
        (company_name, json.dumps(pack), date.today().isoformat()))
    connection.commit()
    connection.close()
    return pack
