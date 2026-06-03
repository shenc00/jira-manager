"""Configuration loaded from environment / .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (parent of this backend package).
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

JIRA_SITE = os.environ.get("JIRA_SITE", "").rstrip("/")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "").strip()
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "").strip()
DEFAULT_PROJECT = os.environ.get("JIRA_PROJECT", "").strip()

ROOT_TYPES = [
    t.strip()
    for t in os.environ.get("JIRA_ROOT_TYPES", "Epic,Task,Story").split(",")
    if t.strip()
]

# Hide issues in Jira's "Done" status category (Completed / Done / Cancelled)
# by default. Can be toggled per-request from the UI.
HIDE_DONE = os.environ.get("JIRA_HIDE_DONE", "true").strip().lower() in (
    "1", "true", "yes", "on",
)

# Where staged changes and the cached tree are persisted.
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
STAGING_FILE = DATA_DIR / "staging.json"


def missing_config() -> list[str]:
    """Return the names of required settings that are not set."""
    required = {
        "JIRA_SITE": JIRA_SITE,
        "JIRA_EMAIL": JIRA_EMAIL,
        "JIRA_API_TOKEN": JIRA_API_TOKEN,
    }
    return [name for name, value in required.items() if not value]
