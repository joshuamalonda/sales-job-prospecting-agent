import os
import sqlite3
from datetime import date

from dotenv import load_dotenv
from openai import OpenAI

from settings import DATABASE_PATH

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAPI_KEY"))


SYSTEM_PROMPT = """
You write short company briefs for a sales rep preparing to cold call.
Use ONLY the information in the job description provided. If something isn't stated, write "Not stated" - never guess.
Plain English. Max 1-2 industry terms. Smart, not childish - the reader may say this to someone who works there.

Rewrite in your own words - never copy marketing language from the job description.
Never use: scattered, streamline, platform, empower, leverage, optimize, innovative, cutting-edge, seamless, fast-paced, solutions.
"Problem they solve" must name a specific pain - who feels it and what it costs them, specifically.
Write it like you're explaining the company to a smart friend over coffee.
"""

# The layout every summary must follow (used in the example and in the real request)
ANSWER_FORMAT = """Return exactly this format:
One-liner: (one sentence on what the company does)
What they do: (2-3 plain-English sentences)
Who they sell to: (type of customer)
Problem they solve: (one sentence)
"""

# A worked example (question + ideal answer) shown to the model before the real company
EXAMPLE_USER_PROMPT = f"""
Company: Wordsmith

Job description:
Wordsmith is the AI-native legal platform empowering in-house legal teams to move at the speed of business. We consolidate scattered legal requests, contracts and knowledge into one seamless workspace, so AI can handle the routine work while lawyers focus on the judgement calls that matter. We're a fast-growing team backed by top-tier investors, partnering with innovative companies across Europe and the US.

{ANSWER_FORMAT}"""

EXAMPLE_ANSWER = """
One-liner: Wordsmith gives in-house legal teams one place to run their work, with AI handling the routine tasks.

What they do: Legal teams get requests from all over the business - Slack, email, random messages - and contracts end up scattered everywhere. Wordsmith pulls all of that into one system and uses AI to deal with the repetitive stuff, like answering common questions and first-pass contract reviews, so the lawyers only spend time on the decisions that need them.

Who they sell to: In-house legal teams at mid-size and large companies.

Problem they solve: In-house lawyers waste hours on repetitive requests and chasing scattered contracts, so work gets slow and companies end up paying expensive outside law firms to cover the overflow.
"""


def create_summaries_table():
    """company_summaries = one saved summary per company, so each company is only paid for once."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS company_summaries (
            company_name TEXT UNIQUE,
            summary TEXT,
            created_at TEXT
        )
    """)
    connection.commit()
    connection.close()


def get_summary(company_name, company_website, description):
    """Return the saved summary, or ask OpenAI for one, save it and return it."""
    # 1. Check the cache (quick read, then close straight away)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    row = connection.execute(
        "SELECT summary FROM company_summaries WHERE company_name = ?", (company_name,)).fetchone()
    connection.close()
    if row:
        return row[0]

    # 2. Not saved yet - ask OpenAI (NO database connection open while we wait)
    user_prompt = f"""
Company: {company_name}

Website: {company_website}

Job description:
{description}

{ANSWER_FORMAT}"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": EXAMPLE_USER_PROMPT},
            {"role": "assistant", "content": EXAMPLE_ANSWER},
            {"role": "user", "content": user_prompt},
        ],
    )
    summary = response.choices[0].message.content

    # 3. Save it. OR IGNORE: if a double-click already saved one, skip quietly instead of crashing
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.execute(
        "INSERT OR IGNORE INTO company_summaries (company_name, summary, created_at) VALUES (?, ?, ?)",
        (company_name, summary, date.today().isoformat()))
    connection.commit()
    connection.close()
    return summary