"""Registry and helpers for the "critical" custom fields and date logic.

Field IDs were discovered from this Jira instance's /field metadata. Each issue
type only allows editing the fields on its screen, so the UI is driven by
editmeta/createmeta rather than assuming every field is writable everywhere.
"""
from __future__ import annotations

from datetime import date, timedelta

# Curated fields surfaced in the item panel, in display order.
# kind: "date" -> YYYY-MM-DD picker; "datetime" -> stored with a time component.
CRITICAL_FIELDS = [
    {"id": "customfield_10015", "name": "Start date", "kind": "date"},
    {"id": "customfield_10525", "name": "Development End Date", "kind": "date"},
    {"id": "customfield_10830", "name": "UAT Start Date", "kind": "date"},
    {"id": "customfield_10831", "name": "UAT End Date", "kind": "date"},
    {"id": "customfield_10178", "name": "Target Completion Date", "kind": "datetime"},
]

TARGET_COMPLETION_FIELD = "customfield_10178"
CRITICAL_IDS = [f["id"] for f in CRITICAL_FIELDS]
_KIND = {f["id"]: f["kind"] for f in CRITICAL_FIELDS}
_NAME = {f["id"]: f["name"] for f in CRITICAL_FIELDS}


def display_value(field_id: str, raw) -> str:
    """Normalise a raw Jira value to what the UI's date input expects."""
    if raw in (None, ""):
        return ""
    kind = _KIND.get(field_id, "text")
    if kind in ("date", "datetime"):
        return str(raw)[:10]  # YYYY-MM-DD
    return raw


def format_custom(field_id: str, value):
    """Convert a UI value into the Jira fields payload value (or None to clear)."""
    if value in (None, "", []):
        return None
    kind = _KIND.get(field_id, "text")
    if kind == "date":
        return str(value)[:10]
    if kind == "datetime":
        # Jira datetime fields (e.g. Target Completion Date) require a time.
        # The UI only captures a date, so default the time to 12:00 (noon) -
        # midday avoids any timezone shift to the previous/next day.
        s = str(value)
        return s if "T" in s else f"{s[:10]}T12:00:00.000+0000"
    return value


# --- date / working-day logic ---------------------------------------------

def to_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def working_days_until(target, today: date | None = None) -> int | None:
    """Working days (Mon-Fri) from ``today`` to ``target``.

    Positive if target is in the future, 0 if it's today, negative if overdue.
    """
    t = to_date(target)
    if t is None:
        return None
    today = today or date.today()
    if t == today:
        return 0
    step = 1 if t > today else -1
    d, n = today, 0
    while d != t:
        d += timedelta(days=step)
        if d.weekday() < 5:  # skip Sat/Sun
            n += step
    return n


def due_flag(target, today: date | None = None) -> tuple[str | None, int | None]:
    """Return (flag, working_days). flag is 'overdue', 'soon' (<=3 wd), or None."""
    n = working_days_until(target, today)
    if n is None:
        return None, None
    if n < 0:
        return "overdue", n
    if n <= 3:
        return "soon", n
    return None, n
