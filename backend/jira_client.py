"""Thin wrapper around the Jira Cloud REST API v3.

Handles authentication, JQL search with pagination, building the
epic -> task -> sub-task tree, and the create/update/transition/comment
operations used when pushing staged changes.
"""
from __future__ import annotations

import random
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from . import config, fields as fields_mod

# Trust the OS certificate store so corporate HTTPS-inspection proxies (whose
# root CA lives in the Windows store, not in certifi) are accepted. Must run
# before any TLS connection is made.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 - truststore is best-effort
    pass


def _parse_dt(value: str | None) -> datetime | None:
    """Parse a Jira timestamp (e.g. 2025-02-20T10:30:00.000+0000)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class JiraError(RuntimeError):
    """Raised when the Jira API returns an error response."""


# --- Atlassian Document Format (ADF) helpers -------------------------------

def text_to_adf(text: str) -> dict:
    """Convert a plain-text string into a minimal ADF document.

    Jira Cloud v3 stores rich-text fields (description, comment) as ADF.
    """
    content: list[dict] = []
    for line in (text or "").split("\n"):
        if line:
            content.append(
                {"type": "paragraph",
                 "content": [{"type": "text", "text": line}]}
            )
        else:
            content.append({"type": "paragraph"})
    if not content:
        content = [{"type": "paragraph"}]
    return {"type": "doc", "version": 1, "content": content}


def adf_to_text(node: Any) -> str:
    """Best-effort flatten of an ADF document (or plain string) to text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        if node.get("type") == "mention":
            return (node.get("attrs") or {}).get("text", "")
        if node.get("type") == "emoji":
            return (node.get("attrs") or {}).get("text", "")
        parts = [adf_to_text(c) for c in node.get("content", [])]
        block = ("paragraph", "doc", "heading", "blockquote",
                 "listItem", "bulletList", "orderedList")
        sep = "\n" if node.get("type") in block else ""
        return sep.join(p for p in parts if p is not None)
    if isinstance(node, list):
        return "".join(adf_to_text(c) for c in node)
    return ""


# --- Client ----------------------------------------------------------------

class JiraClient:
    def __init__(self, site: str, email: str, token: str):
        self.site = site.rstrip("/")
        self.api = f"{self.site}/rest/api/3"
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(email, token)
        self.session.headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )
        # TLS verification: an explicit CA bundle wins; otherwise rely on the
        # injected OS trust store unless verification is explicitly disabled.
        if config.CA_BUNDLE:
            self.session.verify = config.CA_BUNDLE
        elif not config.VERIFY_SSL:
            self.session.verify = False
            try:
                import urllib3
                urllib3.disable_warnings()
            except Exception:  # noqa: BLE001
                pass

    # -- low level ----------------------------------------------------------

    # Jira Cloud occasionally returns transient 502/503/504 (and 429 when rate
    # limited). Retry those a few times with exponential backoff instead of
    # surfacing the error to the user on the first blip.
    _RETRY_STATUS = {429, 502, 503, 504}
    _MAX_RETRIES = 4

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = path if path.startswith("http") else f"{self.api}{path}"
        last_exc: Exception | None = None
        for attempt in range(self._MAX_RETRIES):
            try:
                resp = self.session.request(method, url, timeout=30, **kwargs)
            except requests.RequestException as exc:
                # Network hiccup / timeout — retry the same way as a 5xx.
                last_exc = exc
                if attempt < self._MAX_RETRIES - 1:
                    self._sleep_backoff(attempt)
                    continue
                raise JiraError(f"{method} {url} -> network error: {exc}") from exc

            if resp.status_code in self._RETRY_STATUS and attempt < self._MAX_RETRIES - 1:
                # Honour Retry-After when present, else exponential backoff.
                self._sleep_backoff(attempt, resp.headers.get("Retry-After"))
                continue

            if resp.status_code >= 400:
                detail = resp.text
                try:
                    body = resp.json()
                    detail = body.get("errorMessages") or body.get("errors") or body
                except ValueError:
                    pass
                raise JiraError(f"{method} {url} -> {resp.status_code}: {detail}")
            if resp.status_code == 204 or not resp.content:
                return None
            return resp.json()

        # Should not reach here, but guard just in case.
        raise JiraError(f"{method} {url} -> failed after retries: {last_exc}")

    @staticmethod
    def _sleep_backoff(attempt: int, retry_after: str | None = None) -> None:
        """Sleep before a retry: Retry-After header if given, else backoff."""
        if retry_after:
            try:
                time.sleep(min(float(retry_after), 30.0))
                return
            except (TypeError, ValueError):
                pass
        # Exponential backoff with jitter: ~0.5s, 1s, 2s, 4s (+/- jitter).
        delay = (2 ** attempt) * 0.5 + random.uniform(0, 0.5)
        time.sleep(delay)

    # -- identity / metadata ------------------------------------------------

    def myself(self) -> dict:
        return self._request("GET", "/myself")

    def projects(self) -> list[dict]:
        data = self._request("GET", "/project/search?maxResults=100")
        return [
            {"key": p["key"], "name": p["name"], "id": p["id"]}
            for p in data.get("values", [])
        ]

    def priorities(self) -> list[dict]:
        try:
            data = self._request("GET", "/priority")
            return [{"id": p["id"], "name": p["name"]} for p in data]
        except JiraError:
            return []

    def issue_types_for_project(self, project_key: str) -> list[dict]:
        """Return creatable issue types for a project via createmeta."""
        path = (
            f"/issue/createmeta?projectKeys={project_key}"
            "&expand=projects.issuetypes"
        )
        data = self._request("GET", path)
        projects = data.get("projects", [])
        if not projects:
            return []
        return [
            {"id": it["id"], "name": it["name"], "subtask": it.get("subtask", False)}
            for it in projects[0].get("issuetypes", [])
        ]

    def resolve_user(self, email: str) -> dict | None:
        """Find a user by email (or name). Returns accountId/displayName/email."""
        q = requests.utils.quote(email.strip())
        try:
            data = self._request("GET", f"/user/search?query={q}&maxResults=10")
        except JiraError:
            return None
        if not data:
            return None
        # Prefer an exact email match (emails may be hidden by privacy settings).
        for u in data:
            if (u.get("emailAddress") or "").lower() == email.strip().lower():
                return {"accountId": u["accountId"],
                        "displayName": u.get("displayName", ""),
                        "email": u.get("emailAddress", "")}
        u = data[0]
        return {"accountId": u["accountId"],
                "displayName": u.get("displayName", ""),
                "email": u.get("emailAddress", "")}

    def search_assignable(self, project_key: str, query: str) -> list[dict]:
        path = (
            f"/user/assignable/search?project={project_key}"
            f"&query={requests.utils.quote(query)}&maxResults=20"
        )
        try:
            data = self._request("GET", path)
            return [
                {"accountId": u["accountId"], "displayName": u.get("displayName", "")}
                for u in data
            ]
        except JiraError:
            return []

    # -- search / tree ------------------------------------------------------

    def search(self, jql: str, fields: list[str] | None = None) -> list[dict]:
        """Run JQL via the enhanced search endpoint, following pagination."""
        fields = fields or [
            "summary", "issuetype", "status", "assignee", "parent",
            fields_mod.TARGET_COMPLETION_FIELD,
        ]
        issues: list[dict] = []
        token: str | None = None
        while True:
            body: dict[str, Any] = {"jql": jql, "fields": fields, "maxResults": 100}
            if token:
                body["nextPageToken"] = token
            data = self._request("POST", "/search/jql", json=body)
            issues.extend(data.get("issues", []))
            token = data.get("nextPageToken")
            if not token:
                return issues

    @staticmethod
    def _node(issue: dict) -> dict:
        f = issue.get("fields", {})
        status = f.get("status") or {}
        target = f.get(fields_mod.TARGET_COMPLETION_FIELD)
        flag, wdays = fields_mod.due_flag(target)
        return {
            "key": issue["key"],
            "summary": f.get("summary", ""),
            "type": (f.get("issuetype") or {}).get("name", ""),
            "status": status.get("name", ""),
            "statusCategory": (status.get("statusCategory") or {}).get("key", ""),
            "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
            "targetCompletion": fields_mod.display_value(
                fields_mod.TARGET_COMPLETION_FIELD, target),
            "dueFlag": flag,
            "workingDays": wdays,
            "children": [],
        }

    @staticmethod
    def _is_done(issue: dict) -> bool:
        status = issue.get("fields", {}).get("status") or {}
        return (status.get("statusCategory") or {}).get("key", "") == "done"

    @staticmethod
    def _is_subtask(issue: dict) -> bool:
        return bool((issue.get("fields", {}).get("issuetype") or {}).get("subtask"))

    @staticmethod
    def _parent_key(issue: dict) -> str | None:
        return (issue.get("fields", {}).get("parent") or {}).get("key")

    _TYPE_RANK = {"Epic": 0, "Story": 1, "Task": 1, "Bug": 1}

    def _sort_forest(self, roots: list[dict]) -> None:
        def num(key: str) -> int:
            try:
                return int(key.rsplit("-", 1)[-1])
            except ValueError:
                return 0

        def rank(node: dict) -> int:
            return self._TYPE_RANK.get(node["type"], 1 if not node["type"]
                                       .lower().startswith("sub") else 2)

        def walk(nodes: list[dict]) -> None:
            nodes.sort(key=lambda n: (rank(n), num(n["key"])))
            for n in nodes:
                walk(n["children"])

        walk(roots)

    def build_tree(self, root_types: list[str], hide_done: bool = False,
                   assignee: str | None = None) -> list[dict]:
        """Build the work tree for a user (accountId; defaults to current user).

        Seeds from *every* issue assigned to the user (any type, so sub-tasks are
        included even when their parent epic/story is owned by someone else),
        expands the full descendant breakdown of the user's epics/stories, and
        pulls in any missing ancestors as context so each item nests under its
        real parent (e.g. a story you own appears under its epic, not as a
        separate root).

        When ``hide_done`` is true, issues in the "Done" status category are
        excluded (ancestors included only as needed for structure).
        """
        who = "currentUser()" if not assignee else f'"{assignee}"'
        done_clause = " AND statusCategory != Done" if hide_done else ""

        mine = self.search(f"assignee = {who}{done_clause}")
        mine_by_key = {i["key"]: i for i in mine}

        nodes: dict[str, dict] = {}
        parent_of: dict[str, str] = {}

        def add(issue: dict) -> None:
            key = issue["key"]
            if key not in nodes:
                nodes[key] = self._node(issue)
                pk = self._parent_key(issue)
                if pk:
                    parent_of[key] = pk

        for issue in mine:
            add(issue)

        # Expand descendants of every non-sub-task the user owns (any assignee),
        # so their epics/stories show the full sub-task breakdown.
        expanded: set[str] = set()
        frontier = [k for k, i in mine_by_key.items() if not self._is_subtask(i)]
        while frontier:
            batch = [k for k in frontier if k not in expanded]
            expanded.update(batch)
            if not batch:
                break
            keys = ", ".join(f'"{k}"' for k in batch)
            children = self.search(f"parent in ({keys}) ORDER BY created")
            nxt: list[str] = []
            for ch in children:
                if hide_done and self._is_done(ch):
                    continue
                add(ch)
                if not self._is_subtask(ch):
                    nxt.append(ch["key"])
            frontier = nxt

        # Pull in missing ancestors so items nest under their real parents.
        # Ancestors are included even when they're not assigned to the user and
        # even when completed - they're shown as context for an item you DO own
        # (e.g. your open sub-task under someone else's / a closed epic-story).
        for _ in range(6):  # safety bound on hierarchy depth
            missing = {parent_of[k] for k in list(nodes)
                       if k in parent_of and parent_of[k] not in nodes}
            if not missing:
                break
            keys = ", ".join(f'"{k}"' for k in missing)
            for issue in self.search(f"key in ({keys})"):
                add(issue)

        # Link the forest.
        tree_roots: list[dict] = []
        for key, node in nodes.items():
            pk = parent_of.get(key)
            if pk and pk in nodes:
                nodes[pk]["children"].append(node)
            else:
                tree_roots.append(node)

        self._sort_forest(tree_roots)
        return tree_roots

    # -- single issue -------------------------------------------------------

    def get_issue(self, key: str) -> dict:
        base = [
            "summary", "description", "issuetype", "status", "assignee",
            "priority", "labels", "duedate", "parent", "comment", "created",
            "updated", "reporter", "timetracking",
        ]
        fields = ",".join(base + fields_mod.CRITICAL_IDS)
        data = self._request("GET", f"/issue/{key}?fields={fields}")
        f = data.get("fields", {})
        comments = [
            {
                "author": (c.get("author") or {}).get("displayName", ""),
                "created": c.get("created", ""),
                "body": adf_to_text(c.get("body")),
            }
            for c in (f.get("comment") or {}).get("comments", [])
        ]

        # Which critical fields are editable for THIS issue (per editmeta).
        try:
            editmeta = self._request("GET", f"/issue/{key}/editmeta").get("fields", {})
        except JiraError:
            editmeta = {}
        critical = [
            {
                "id": spec["id"],
                "name": spec["name"],
                "kind": spec["kind"],
                "value": fields_mod.display_value(spec["id"], f.get(spec["id"])),
                "editable": spec["id"] in editmeta,
            }
            for spec in fields_mod.CRITICAL_FIELDS
        ]

        tt = f.get("timetracking") or {}
        timetracking = {
            "originalEstimate": tt.get("originalEstimate", ""),
            "remainingEstimate": tt.get("remainingEstimate", ""),
            "timeSpent": tt.get("timeSpent", ""),
            "editable": "timetracking" in editmeta,
        }

        target = f.get(fields_mod.TARGET_COMPLETION_FIELD)
        flag, wdays = fields_mod.due_flag(target)
        return {
            "key": data["key"],
            "summary": f.get("summary", ""),
            "description": adf_to_text(f.get("description")),
            "type": (f.get("issuetype") or {}).get("name", ""),
            "status": (f.get("status") or {}).get("name", ""),
            "assignee": (f.get("assignee") or {}),
            "priority": (f.get("priority") or {}).get("name", ""),
            "labels": f.get("labels", []),
            "duedate": f.get("duedate"),
            "parent": (f.get("parent") or {}).get("key"),
            "reporter": (f.get("reporter") or {}).get("displayName", ""),
            "project": data["key"].split("-")[0],
            "comments": comments,
            "critical": critical,
            "timetracking": timetracking,
            "dueFlag": flag,
            "workingDays": wdays,
        }

    def get_labels(self) -> list[str]:
        """All labels defined in the instance, for the selection dropdown."""
        labels: list[str] = []
        start = 0
        while True:
            data = self._request("GET", f"/label?maxResults=1000&startAt={start}")
            labels.extend(data.get("values", []))
            if data.get("isLast", True) or not data.get("values"):
                break
            start += len(data["values"])
        return labels

    def createmeta_field_ids(self, project_key: str, issuetype: str) -> set[str]:
        """Field IDs creatable for an issue type (used to drive the create form)."""
        path = (
            f"/issue/createmeta?projectKeys={project_key}"
            f"&issuetypeNames={requests.utils.quote(issuetype)}"
            "&expand=projects.issuetypes.fields"
        )
        data = self._request("GET", path)
        projects = data.get("projects", [])
        if not projects:
            return set()
        types = projects[0].get("issuetypes", [])
        if not types:
            return set()
        return set(types[0].get("fields", {}).keys())

    def latest_comment(self, key: str) -> dict | None:
        """Most recent comment, plus the combined text of recent comments.

        ``text`` is the latest comment (for display); ``allText`` concatenates
        recent comments so callers can scan them (e.g. for delay mentions).
        """
        try:
            data = self._request(
                "GET", f"/issue/{key}/comment?maxResults=30&orderBy=-created")
        except JiraError:
            return None
        comments = data.get("comments", [])
        if not comments:
            return None
        latest = comments[0]
        all_text = "  ".join(adf_to_text(c.get("body")) for c in comments)
        return {
            "author": (latest.get("author") or {}).get("displayName", ""),
            "date": (latest.get("created") or "")[:10],
            "text": adf_to_text(latest.get("body")),
            "allText": all_text,
        }

    def recent_comments(self, key: str, limit: int = 3,
                        within_days: int = 28) -> dict:
        """Latest ``limit`` comments created within ``within_days`` (default:
        last 3 within the last 4 weeks of *now*), newest first.

        If there are no comments in that window but the issue does have
        comments, the single most-recent comment is returned (``fallback``).
        ``allText`` is every comment's text combined (for the delay scan).

        The ordering is computed here rather than relying on Jira's response
        order, so the window filter is reliable.
        """
        try:
            data = self._request("GET", f"/issue/{key}/comment?maxResults=100")
        except JiraError:
            return {"recent": [], "fallback": False, "allText": ""}
        comments = data.get("comments", [])

        def created_of(c):
            return fields_mod.to_date(c.get("created")) or date.min

        ordered = sorted(comments, key=created_of, reverse=True)  # newest first

        def fmt(c):
            return {
                "author": (c.get("author") or {}).get("displayName", ""),
                "date": (c.get("created") or "")[:10],
                "text": adf_to_text(c.get("body")),
            }

        cutoff = date.today() - timedelta(days=within_days)
        within = [c for c in ordered if created_of(c) >= cutoff]

        if within:
            recent, fallback = [fmt(c) for c in within[:limit]], False
        elif ordered:
            recent, fallback = [fmt(ordered[0])], True  # latest, outside window
        else:
            recent, fallback = [], False

        all_text = "  ".join(adf_to_text(c.get("body")) for c in ordered)
        return {"recent": recent, "fallback": fallback, "allText": all_text}

    def get_transitions(self, key: str) -> list[dict]:
        data = self._request("GET", f"/issue/{key}/transitions")
        return [
            {"id": t["id"], "name": t["name"],
             "to": (t.get("to") or {}).get("name", "")}
            for t in data.get("transitions", [])
        ]

    # -- mutations ----------------------------------------------------------

    def create_issue(self, fields: dict) -> dict:
        """Create an issue. ``fields`` is the raw Jira fields object."""
        return self._request("POST", "/issue", json={"fields": fields})

    def update_issue(self, key: str, fields: dict) -> None:
        self._request("PUT", f"/issue/{key}", json={"fields": fields})

    def transition_issue(self, key: str, transition_id: str) -> None:
        self._request(
            "POST", f"/issue/{key}/transitions",
            json={"transition": {"id": transition_id}},
        )

    def transition_issue_by_name(self, key: str, status_name: str) -> bool:
        """Transition by target status name. Returns False if not available."""
        for t in self.get_transitions(key):
            if (t["to"].lower() == status_name.lower()
                    or t["name"].lower() == status_name.lower()):
                self.transition_issue(key, t["id"])
                return True
        return False

    def add_comment(self, key: str, text: str) -> None:
        self._request(
            "POST", f"/issue/{key}/comment",
            json={"body": text_to_adf(text)},
        )

    # -- stale "On Hold" detection -----------------------------------------

    def entered_status_date(self, key: str, status_name: str) -> datetime | None:
        """When the issue most recently transitioned INTO ``status_name``.

        Reads the issue changelog. Returns None if there is no such transition
        (e.g. it was created directly in that status).
        """
        cl = self._request("GET", f"/issue/{key}/changelog?maxResults=100")
        latest: datetime | None = None
        for history in cl.get("values", []):
            for item in history.get("items", []):
                if item.get("field") == "status" and item.get("toString") == status_name:
                    ts = _parse_dt(history.get("created"))
                    if ts and (latest is None or ts > latest):
                        latest = ts
        return latest

    def find_stale_onhold(self, months: int, onhold_status: str) -> list[dict]:
        """Items assigned to me that have been in ``onhold_status`` too long.

        Duration is measured from when the issue entered the on-hold status
        (per changelog), falling back to its creation date.
        """
        items = self.search(
            f'assignee = currentUser() AND status = "{onhold_status}" ORDER BY updated',
            fields=["summary", "issuetype", "status", "created"],
        )
        now = datetime.now(timezone.utc)
        cutoff_days = months * 30.4
        stale: list[dict] = []
        for issue in items:
            key = issue["key"]
            f = issue.get("fields", {})
            since = self.entered_status_date(key, onhold_status) or _parse_dt(f.get("created"))
            if since is None:
                continue
            age_days = (now - since).days
            if age_days >= cutoff_days:
                stale.append({
                    "key": key,
                    "summary": f.get("summary", ""),
                    "type": (f.get("issuetype") or {}).get("name", ""),
                    "since": since.date().isoformat(),
                    "months": round(age_days / 30.4, 1),
                })
        return stale


def from_config() -> JiraClient:
    return JiraClient(config.JIRA_SITE, config.JIRA_EMAIL, config.JIRA_API_TOKEN)
