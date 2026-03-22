# config/settings.py
#
# Central configuration for the entire application.
#
# CONCEPT — Why centralise config?
# Instead of scattering API keys, URLs, and thresholds across every file,
# we load everything once here. Every other file imports from this module.
# This means if a URL changes or you want to tune the scoring threshold,
# there's exactly ONE place to change it.
#
# CONCEPT — python-dotenv
# The load_dotenv() call reads your .env file and loads every key=value
# pair into os.environ. After that, os.getenv("KEY") works anywhere.
# In production (Cloud Run), environment variables are injected by GCP
# directly — load_dotenv() safely does nothing in that case.

import os
from dotenv import load_dotenv

# Load .env file into environment variables
# This is a no-op in production where env vars are set by GCP
load_dotenv()


# ---------------------------------------------------------------------------
# API KEYS
# os.getenv(key, default) returns the value or the default if not set.
# We use empty string as default so missing keys fail loudly at runtime
# (an empty string passed to an API call will get a clear auth error)
# rather than silently with None.
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
APIFY_API_TOKEN     = os.getenv("APIFY_API_TOKEN", "")
TAVILY_API_KEY      = os.getenv("TAVILY_API_KEY", "")
PROXYCURL_API_KEY   = os.getenv("PROXYCURL_API_KEY", "")
HUNTER_API_KEY      = os.getenv("HUNTER_API_KEY", "")

# Gmail OAuth
GMAIL_CLIENT_ID     = os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")
GMAIL_REDIRECT_URI  = os.getenv("GMAIL_REDIRECT_URI", "http://localhost:8080")

# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ---------------------------------------------------------------------------
# GCP
# ---------------------------------------------------------------------------

GCP_PROJECT_ID       = os.getenv("GCP_PROJECT_ID", "")
GCP_REGION           = os.getenv("GCP_REGION", "asia-south1")
CLOUD_STORAGE_BUCKET = os.getenv("CLOUD_STORAGE_BUCKET", "")

# ---------------------------------------------------------------------------
# APP
# ---------------------------------------------------------------------------

APP_ENV = os.getenv("APP_ENV", "development")
IS_PRODUCTION = APP_ENV == "production"

# ---------------------------------------------------------------------------
# SCRAPING CONFIG
# ---------------------------------------------------------------------------

# Keywords used to search job portals
# Edit these to broaden or narrow your job search
JOB_SEARCH_KEYWORDS = [
    "AI Engineer",
    "LLM Engineer",
    "Agentic AI Engineer",
    "GenAI Engineer",
    "Applied AI Engineer",
    "ML Engineer",
]

# Locations to search
JOB_SEARCH_LOCATIONS = [
    "Bengaluru",
    "Remote",
    "India",
]

# Max jobs to fetch per source per run
# Keep this low during development to avoid burning API credits
MAX_JOBS_PER_SOURCE = 20

# ---------------------------------------------------------------------------
# SCORING CONFIG
# ---------------------------------------------------------------------------

# Jobs with score >= this threshold are marked recommended=True
# and surfaced prominently in the dashboard
SCORING_THRESHOLD = 60

# ---------------------------------------------------------------------------
# OUTREACH CONFIG
# ---------------------------------------------------------------------------

# Hard cap on emails sent per day — safety limit to protect sender reputation
MAX_EMAILS_PER_DAY = 20

# Minimum delay between email sends (seconds)
# Randomised between this and EMAIL_SEND_DELAY_MAX
EMAIL_SEND_DELAY_MIN = 120   # 2 minutes
EMAIL_SEND_DELAY_MAX = 300   # 5 minutes


# ---------------------------------------------------------------------------
# RESUME
# ---------------------------------------------------------------------------
# Path to your resume — used by ScoringAgent to score jobs
RESUME_PATH = "config/resume.md"