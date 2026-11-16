"""All of Landly's settings in one place. Each one comes from an environment variable
(the .env file locally, the Variables tab on Railway), with a safe default where that makes sense."""
import os

from dotenv import load_dotenv

load_dotenv()

# Where the SQLite database lives. Locally: landly.db in this folder. On Railway: on the volume, e.g. /data/landly.db
DATABASE_PATH = os.getenv("DATABASE_PATH", "landly.db")

# Login for the whole site. main.py refuses to start if either is missing.
APP_USERNAME = os.getenv("APP_USERNAME")
APP_PASSWORD = os.getenv("APP_PASSWORD")

# Daily spending caps: only NEW paid work counts (cached plans and contacts are free)
MAX_PLANS_PER_DAY = int(os.getenv("MAX_PLANS_PER_DAY", "10"))
MAX_CONTACT_LOOKUPS_PER_DAY = int(os.getenv("MAX_CONTACT_LOOKUPS_PER_DAY", "20"))

# Turn on the daily job refresh inside the web app (true on Railway, off on my laptop)
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER") == "true"
