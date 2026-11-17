"""Regression tests for the prospecting plan. Run after every change:

    python tests/check_plans.py                    FREE - replays saved inputs, no API calls at all
    python tests/check_plans.py --only Vertice     FREE - just one company
    python tests/check_plans.py --refresh-openai   ~1p per company - only needed when a prompt changed
                                             (re-asks OpenAI where the saved answer no longer matches)
    python tests/check_plans.py --record Vertice   PAID (~$0.20 Exa) - records fresh real inputs for one company

How it works: tests/golden_plans/<company>.json holds everything a real run fetched - the website text,
the job ad, Exa's company and news results, and OpenAI's answers. Replaying them runs the real pipeline
code (build_pack) on the same inputs every time, then checks the plan against the rules below and the
hand-written answers in tests/golden_plans/expectations.json."""
import argparse
import contextlib
import copy
import hashlib
import io
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import requests

# This file lives in tests/, so tell Python to also look one folder up for the app's own files
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import prospecting
from settings import DATABASE_PATH

GOLDEN_DIR = Path(__file__).parent / "golden_plans"
EXPECTATIONS_FILE = GOLDEN_DIR / "expectations.json"
CLAIM_ANSWERS_FILE = GOLDEN_DIR / "claim_cases_openai.json"
COMPANIES = ["Triple Whale", "Vertice", "PlainID", "Everfield"]

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]
NAME_FILLER_WORDS = {"ltd", "limited", "group", "inc", "plc", "uk", "the", "co", "llc", "gmbh", "and", "holdings"}


class MissingRecording(Exception):
    """OpenAI was asked something that isn't saved - a prompt changed since the inputs were recorded."""


# ---------- Saved files ----------

def fixture_path(company):
    """'Triple Whale' -> tests/golden_plans/triple_whale.json"""
    slug = re.sub(r"[^a-z0-9]+", "_", company.lower()).strip("_")
    return GOLDEN_DIR / f"{slug}.json"


def load_json(path):
    with open(path) as json_file:
        return json.load(json_file)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as json_file:
        json.dump(data, json_file, indent=1, ensure_ascii=False)


def prompt_key(prompt):
    """A short fingerprint of a prompt. The same prompt always gives the same key, so a saved answer
    is found again; any change to the prompt gives a new key."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def fresh_copy(data):
    """A deep copy, so the pipeline can't change the saved data while it works with it."""
    return copy.deepcopy(data)


# ---------- Recording real inputs (PAID) ----------

def load_job(company):
    """The company's job from our database: website, location and title."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    row = connection.execute(
        "SELECT company_website, place, title FROM jobs WHERE company_name = ? LIMIT 1", (company,)).fetchone()
    connection.close()
    if not row:
        raise ValueError(f"No job for {company} in the database")
    return row


def record_inputs(company, save_plan=False):
    """Run the REAL pipeline once (paid Exa + OpenAI) and save everything it fetched.
    save_plan=False: Blitz is skipped (no credits) and the plan isn't saved.
    save_plan=True: a normal full rebuild that also saves the plan (used for a real rebuild)."""
    website, place, title = load_job(company)
    territory = prospecting.territory_for(place, title)
    fixture = {
        "company": company, "website": website, "territory": territory,
        "recorded_on": date.today().isoformat(),
        "website_text": "", "job_description": "", "candidates": [], "evidence": {}, "openai": {},
        "buyers": {},
    }
    originals = save_originals()

    def recording_website_text(name, domain):
        fixture["website_text"] = originals["get_website_text"](name, domain)
        return fixture["website_text"]

    def recording_job_description(name):
        fixture["job_description"] = originals["get_job_description"](name)
        return fixture["job_description"]

    def recording_candidates(queries, exclude_domain):
        found = originals["find_candidates"](queries, exclude_domain)
        known_urls = [candidate["url"] for candidate in fixture["candidates"]]
        for candidate in found:
            if candidate["url"] not in known_urls:
                fixture["candidates"].append(fresh_copy(candidate))
        return found

    def recording_evidence(candidate, trigger_types):
        evidence = originals["find_trigger_evidence"](candidate, trigger_types)
        fixture["evidence"][candidate["url"]] = fresh_copy(evidence)
        return evidence

    def recording_openai(prompt):
        answer = originals["ask_openai_for_json"](prompt)
        fixture["openai"][prompt_key(prompt)] = {"start_of_prompt": prompt[:80], "answer": fresh_copy(answer)}
        return answer

    def recording_buyer(account_url, buyer_titles, fallback_titles):
        buyer = originals["find_buyer"](account_url, buyer_titles, fallback_titles)
        fixture["buyers"][account_url] = fresh_copy(buyer)
        return buyer

    prospecting.get_website_text = recording_website_text
    prospecting.get_job_description = recording_job_description
    prospecting.find_candidates = recording_candidates
    prospecting.find_trigger_evidence = recording_evidence
    prospecting.ask_openai_for_json = recording_openai
    if save_plan:
        prospecting.find_buyer = recording_buyer                        # real Blitz lookup, saved for replays
    else:
        prospecting.find_buyer = lambda *args, **kwargs: None          # no Blitz credits for recordings
    try:
        if save_plan:
            pack = prospecting.get_pack(company, website, territory, refresh=True)
        else:
            pack = prospecting.build_pack(company, website, territory)
    finally:
        restore_originals(originals)
        # Saved even if the run crashed, so paid-for Exa results are never thrown away
        save_json(fixture_path(company), fixture)
        print(f"Saved inputs for {company} to {fixture_path(company)}")
    return pack


# ---------- Replaying saved inputs (FREE) ----------

def save_originals():
    """Remember the real pipeline functions, so they can be put back after recording or replaying."""
    names = ["get_website_text", "get_job_description", "find_candidates", "find_trigger_evidence",
             "ask_openai_for_json", "find_buyer"]
    return {name: getattr(prospecting, name) for name in names}


def restore_originals(originals):
    for name, function in originals.items():
        setattr(prospecting, name, function)


def no_paid_calls(*args, **kwargs):
    raise RuntimeError("tests/check_plans.py tried a real API call - every input should come from the saved file")


def replay(company, refresh_openai=False):
    """Run the real pipeline on the saved inputs. Returns (plan, log text, missing OpenAI answers)."""
    fixture = load_json(fixture_path(company))
    saved_answers = fixture["openai"]
    used_answers = {}
    missing = []
    originals = save_originals()
    real_requests = (requests.get, requests.post)

    def saved_openai(prompt):
        key = prompt_key(prompt)
        if key in saved_answers:
            used_answers[key] = saved_answers[key]
            return fresh_copy(saved_answers[key]["answer"])
        if not refresh_openai:
            missing.append(prompt[:80])
            raise MissingRecording(prompt[:80])
        answer = originals["ask_openai_for_json"](prompt)            # small real OpenAI call
        used_answers[key] = {"start_of_prompt": prompt[:80], "answer": fresh_copy(answer)}
        return answer

    def saved_candidates(queries, exclude_domain):
        return [fresh_copy(candidate) for candidate in fixture["candidates"] if exclude_domain not in candidate["url"]]

    prospecting.get_website_text = lambda name, domain: fixture["website_text"]
    prospecting.get_job_description = lambda name: fixture["job_description"]
    prospecting.find_candidates = saved_candidates
    prospecting.find_trigger_evidence = lambda candidate, trigger_types: fresh_copy(
        fixture["evidence"].get(candidate["url"], []))
    prospecting.ask_openai_for_json = saved_openai
    # The buyer found when the inputs were recorded (None if Blitz was skipped) - it appears in the email prompt
    prospecting.find_buyer = lambda account_url, *args, **kwargs: fresh_copy(
        fixture.get("buyers", {}).get(account_url))
    requests.get = requests.post = no_paid_calls                  # Exa, Blitz, websites: never called
    completions = prospecting.client.chat.completions
    real_openai_call = completions.create
    if not refresh_openai:
        completions.create = no_paid_calls                         # free mode: OpenAI can't be reached either

    log = io.StringIO()
    pack = None
    try:
        with contextlib.redirect_stdout(log):
            pack = prospecting.build_pack(company, fixture["website"], fixture["territory"])
    except MissingRecording:
        pass
    finally:
        restore_originals(originals)
        requests.get, requests.post = real_requests
        completions.create = real_openai_call

    if refresh_openai and not missing:
        fixture["openai"] = used_answers                         # keep only answers the current code uses
        save_json(fixture_path(company), fixture)
    return pack, log.getvalue(), missing


# ---------- The checks ----------

def name_words(account):
    """Distinctive words for an account: from its name and its website, e.g. 'Ageas UK' -> {'ageas'}."""
    words = set()
    for word in re.findall(r"[a-z0-9]+", (account.get("name") or "").lower()):
        if len(word) >= 3 and word not in NAME_FILLER_WORDS:
            words.add(word)
    domain = prospecting.to_domain(account.get("url") or "")
    if domain:
        words.add(domain.split(".")[0])                       # "boozt.com" -> "boozt"
    return words


def date_problems(account):
    """Months and years named in the trigger must appear in the evidence, or match when it was published
    (the month of publishing, or the month before - "last week")."""
    trigger = (account.get("trigger") or "").lower()
    evidence_text = f"{account.get('evidence_title', '')} {account.get('evidence_snippet', '')}".lower()
    published = account.get("evidence_date") or ""
    problems = []

    for year in re.findall(r"\b20\d\d\b", trigger):
        if year not in evidence_text and not published.startswith(year):
            problems.append(f"year {year} isn't in the evidence")

    published_month = int(published[5:7]) if len(published) >= 7 else None
    for number, month in enumerate(MONTHS, 1):
        if not re.search(rf"\b{month}\b", trigger):
            continue
        matches_publish_date = published_month in (number, number % 12 + 1)
        if month not in evidence_text and not matches_publish_date:
            problems.append(f"'{month.title()}' isn't in the evidence (published {published or 'unknown'})")
    return problems


def check_pack(company, pack, expectations):
    """Return (failures, warnings) for one plan."""
    failures, warnings = [], []
    icp = pack["icp"]
    expected = expectations["companies"][company]

    # ICP
    trigger_count = len(icp.get("trigger_types") or [])
    if trigger_count < prospecting.MIN_TRIGGERS:
        failures.append(f"only {trigger_count} trigger types (need {prospecting.MIN_TRIGGERS}+)")
    target = (icp.get("target_customers") or "").lower()
    if not any(word in target for word in expected["business_model_words"]):
        failures.append(f"target_customers doesn't name a business model: {icp.get('target_customers')!r}")
    if icp.get("segment") not in prospecting.SEGMENT_RANGES:
        failures.append(f"segment is {icp.get('segment')!r}")

    # Accounts
    minimum = expected.get("min_accounts", 0)
    if len(pack["accounts"]) < minimum:
        failures.append(f"only {len(pack['accounts'])} account(s) - these saved inputs should give at least {minimum}")
    banned_names = [name.lower() for name in expected["forbidden_accounts"] + [company]
                    + list(icp.get("companies_in_job_ad") or [])]
    for account in pack["accounts"]:
        name = account.get("name") or ""
        label = f"{name}:"
        url = (account.get("url") or "").lower()
        for banned in banned_names:
            if banned and (banned in name.lower() or banned.replace(" ", "") in url):
                failures.append(f"{label} is a vendor/competitor/the employer - must never be an account")
                break

        evidence_text = " ".join([account.get("evidence_title") or "", account.get("evidence_snippet") or "",
                                  account.get("evidence_url") or ""]).lower()
        if not any(word in evidence_text for word in name_words(account)):
            failures.append(f"{label} the evidence never mentions this company")
        for problem in date_problems(account):
            failures.append(f"{label} trigger date not supported - {problem}")

        # Banned words: a FAIL if they slipped through silently, only a warning if flagged for review
        has_review = bool(account.get("review_notes"))
        word_problems = []
        if account.get("opening_line"):
            opener_problem = prospecting.opener_precheck(account["opening_line"])
            if opener_problem and "banned" in opener_problem:
                word_problems.append(f"opening line {opener_problem}")
        why_now_banned = prospecting.why_now_problems(account.get("why_now"))
        if why_now_banned:
            word_problems.append(f"why_now uses {', '.join(why_now_banned)}")
        for problem in word_problems:
            if has_review:
                warnings.append(f"{label} {problem} (flagged for review)")
            else:
                failures.append(f"{label} {problem}")

    # Outreach
    outreach = pack.get("outreach")
    if outreach:
        email_text = outreach["email"].lower()
        call_text = f"{outreach['call']['reason']} {outreach['call']['question']}".lower()
        banned = sorted({phrase for phrase in prospecting.EMAIL_BANNED if phrase in email_text}
                        | {phrase for phrase in prospecting.CALL_BANNED if phrase in call_text})
        if banned:
            if outreach.get("review_notes"):
                warnings.append(f"outreach uses {', '.join(banned)} (flagged for review)")
            else:
                failures.append(f"outreach uses {', '.join(banned)}")
        if not outreach["call"]["reason"]:
            failures.append("outreach: call reason is empty")
    elif pack["accounts"]:
        warnings.append("no outreach (dropped for facts, or failed)")
    return failures, warnings


def check_claim_cases(expectations, refresh_openai=False):
    """Run the claim verifier on the hand-written cases (false claims must fail, the true one must pass)."""
    cases = expectations["claim_cases"]
    saved = load_json(CLAIM_ANSWERS_FILE) if CLAIM_ANSWERS_FILE.exists() else {}
    used = {}
    failures = []
    original_ask = prospecting.ask_openai_for_json

    def saved_openai(prompt):
        key = prompt_key(prompt)
        if key in saved:
            used[key] = saved[key]
            return fresh_copy(saved[key]["answer"])
        if not refresh_openai:
            raise MissingRecording(prompt[:80])
        answer = original_ask(prompt)
        used[key] = {"start_of_prompt": prompt[:80], "answer": fresh_copy(answer)}
        return answer

    prospecting.ask_openai_for_json = saved_openai
    try:
        for case in cases["cases"]:
            try:
                verdict = prospecting.verify_claim(cases["company_name"], cases["icp"], case["account"],
                                                   case["claim"], case["evidence"])
            except MissingRecording:
                failures.append(f"{case['name']}: verifier answer not recorded - run with --refresh-openai")
                continue
            expected_check = case.get("expect_failed_check")
            if verdict["supported"] != case["expect_supported"]:
                failures.append(f"{case['name']}: expected supported={case['expect_supported']}, "
                                f"got {verdict['supported']} ({verdict['problem']})")
            elif expected_check and expected_check not in verdict["failed"]:
                # Rejected, but for the wrong reason - it would let a similar claim through
                failures.append(f"{case['name']}: rejected for the wrong reason - expected {expected_check}, "
                                f"got {verdict['failed']} ({verdict['problem']})")
            else:
                print(f"    ok  {case['name']}" + (f" -> {verdict['problem']}" if verdict["problem"] else ""))
    finally:
        prospecting.ask_openai_for_json = original_ask
    if refresh_openai:
        save_json(CLAIM_ANSWERS_FILE, used)
    return failures


def interesting_log_lines(log):
    """The lines worth showing: what was dropped or excluded, and why."""
    keep = ("Dropped", "Excluded", "Removed trigger", "Account size", "Outreach", "Only", "Warning", "Segment")
    return [line for line in log.splitlines() if line.startswith(keep)]


def main():
    parser = argparse.ArgumentParser(description="Regression tests for the prospecting plan")
    parser.add_argument("--only", help="check just this company")
    parser.add_argument("--refresh-openai", action="store_true",
                        help="re-ask OpenAI where a prompt changed (about 1p per company)")
    parser.add_argument("--record", metavar="COMPANY", help="PAID: record fresh real inputs for one company")
    parser.add_argument("--verbose", action="store_true", help="show every drop/exclusion line")
    args = parser.parse_args()

    if args.record:
        record_inputs(args.record)
        return

    expectations = load_json(EXPECTATIONS_FILE)
    companies = [args.only] if args.only else COMPANIES
    all_passed = True

    print("Claim verifier cases")
    claim_failures = check_claim_cases(expectations, args.refresh_openai)
    for failure in claim_failures:
        print(f"    FAIL {failure}")
    all_passed = all_passed and not claim_failures

    for company in companies:
        if not fixture_path(company).exists():
            print(f"\n{company}: SKIP - no saved inputs (run: python tests/check_plans.py --record \"{company}\")")
            all_passed = False
            continue
        pack, log, missing = replay(company, args.refresh_openai)
        if missing:
            print(f"\n{company}: FAIL - {len(missing)} OpenAI answer(s) not recorded because a prompt changed.\n"
                  f"    Run: python tests/check_plans.py --refresh-openai   (about 1p per company)")
            all_passed = False
            continue
        failures, warnings = check_pack(company, pack, expectations)
        status = "PASS" if not failures else "FAIL"
        all_passed = all_passed and not failures
        icp = pack["icp"]
        print(f"\n{company}: {status}")
        print(f"    segment: {icp.get('segment_label')} | triggers: {len(icp.get('trigger_types') or [])}")
        print(f"    target customers: {icp.get('target_customers')}")
        print(f"    accounts: {', '.join(a['name'] for a in pack['accounts']) or 'none'}"
              f" | outreach: {'yes' if pack.get('outreach') else 'no'}")
        if args.verbose:
            for line in interesting_log_lines(log):
                print(f"      {line}")
        for failure in failures:
            print(f"    FAIL {failure}")
        for warning in warnings:
            print(f"    warn {warning}")

    print("\nALL PASSED" if all_passed else "\nSOME CHECKS FAILED")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
