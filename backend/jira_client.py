"""Thin wrapper around the Jira Cloud REST API v3.

Handles authentication, JQL search with pagination, building the
epic -> task -> sub-task tree, and the create/update/transition/comment
operations used when pushing staged changes.
"""
from __future__ import annotations

from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from . import config


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
        parts = [adf_to_text(c) for c in node.get("content", [])]
        sep = "\n" if node.get("type") in ("paragraph", "doc") else ""
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

    # -- low level ----------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = path if path.startswith("http") else f"{self.api}{path}"
        resp = self.session.request(method, url, timeout=30, **kwargs)
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
        fields = fields or ["summary", "issuetype", "status", "assignee", "parent"]
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
        return {
            "key": issue["key"],
            "summary": f.get("summary", ""),
            "type": (f.get("issuetype") or {}).get("name", ""),
            "status": (f.get("status") or {}).get("name", ""),
            "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
            "children": [],
        }

    def build_tree(self, root_types: list[str]) -> list[dict]:
        """Return roots (epics/tasks assigned to me) with descendants nested.

        Roots are issues assigned to the current user whose type is in
        ``root_types``. Children are fetched level-by-level via the ``parent``
        field, so sub-tasks (even if assigned to others) are included.
        """
        types = ", ".join(f'"{t}"' for t in root_types)
        roots = self.search(
            f"assignee = currentUser() AND issuetype in ({types}) "
            "ORDER BY issuetype, created"
        )
        nodes: dict[str, dict] = {}
        tree_roots: list[dict] = []
        for issue in roots:
            node = self._node(issue)
            nodes[issue["key"]] = node
            tree_roots.append(node)

        frontier = list(nodes.keys())
        seen = set(frontier)
        while frontier:
            keys = ", ".join(f'"{k}"' for k in frontier)
            children = self.search(f"parent in ({keys}) ORDER BY issuetype, created")
            next_frontier: list[str] = []
            for child in children:
                key = child["key"]
                if key in seen:
                    continue
                seen.add(key)
                node = self._node(child)
                nodes[key] = node
                parent_key = (child["fields"].get("parent") or {}).get("key")
                if parent_key in nodes:
                    nodes[parent_key]["children"].append(node)
                else:
                    tree_roots.append(node)
                next_frontier.append(key)
            frontier = next_frontier
        return tree_roots

    # -- single issue -------------------------------------------------------

    def get_issue(self, key: str) -> dict:
        fields = (
            "summary,description,issuetype,status,assignee,priority,labels,"
            "duedate,parent,comment,created,updated,reporter"
        )
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
        }

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


def from_config() -> JiraClient:
    return JiraClient(config.JIRA_SITE, config.JIRA_EMAIL, config.JIRA_API_TOKEN)
