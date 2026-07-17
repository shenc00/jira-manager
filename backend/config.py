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


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# --- Auto-cancel stale "On Hold" items -------------------------------------
# When enabled, items assigned to you that have been in ONHOLD_STATUS for more
# than ONHOLD_MONTHS are transitioned to CANCEL_STATUS. This is an irreversible
# write to Jira, so it is OFF by default in code; enable it in your own .env.
AUTO_CANCEL_STALE_ONHOLD = _as_bool(
    os.environ.get("JIRA_AUTO_CANCEL_STALE_ONHOLD", ""), default=False
)
ONHOLD_STATUS = os.environ.get("JIRA_ONHOLD_STATUS", "On Hold").strip()
CANCEL_STATUS = os.environ.get("JIRA_CANCEL_STATUS", "Cancelled").strip()
ONHOLD_MONTHS = int(os.environ.get("JIRA_ONHOLD_MONTHS", "6") or "6")
# Safety valve: if more than this many items would be auto-cancelled in one
# scan, pause and require explicit confirmation instead of mass-cancelling.
AUTO_CANCEL_CAP = int(os.environ.get("JIRA_AUTO_CANCEL_CAP", "25") or "25")

# --- TLS / corporate proxy -------------------------------------------------
# Corporate networks that intercept HTTPS present a self-signed root CA. The
# app injects the OS trust store (truststore) so that CA is trusted. These are
# fallbacks: point JIRA_CA_BUNDLE at a .pem, or set JIRA_VERIFY_SSL=false to
# skip verification entirely (last resort).
VERIFY_SSL = _as_bool(os.environ.get("JIRA_VERIFY_SSL", "true"), default=True)
CA_BUNDLE = os.environ.get("JIRA_CA_BUNDLE", "").strip()

# Where staged changes and the cached tree are persisted.
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
STAGING_FILE = DATA_DIR / "staging.json"

# Audit trail of every auto-cancellation (one JSON line per item).
AUDIT_LOG = DATA_DIR / "auto_cancel.log"

# Local overlay for Component / Developer / Assigned Group (see local_fields.py).
LOCAL_FIELDS_FILE = DATA_DIR / "local_fields.json"


def missing_config() -> list[str]:
    """Return the names of required settings that are not set."""
    required = {
        "JIRA_SITE": JIRA_SITE,
        "JIRA_EMAIL": JIRA_EMAIL,
        "JIRA_API_TOKEN": JIRA_API_TOKEN,
    }
    return [name for name, value in required.items() if not value]
