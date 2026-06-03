"""FastAPI application: serves the browser UI and the JSON API.

The tree is cached in memory after each fetch so that staged (not-yet-pushed)
changes can be overlaid without re-hitting Jira on every render.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .jira_client import JiraError, from_config
from .staging import StagingStore

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Jira Manager")
staging = StagingStore(config.STAGING_FILE)

# In-memory cache of the last fetched tree.
_cache: dict[str, Any] = {"tree": None, "me": None}


def client():
    missing = config.missing_config()
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"Missing config: {', '.join(missing)}. "
                   "Copy .env.example to .env and fill it in.",
        )
    return from_config()


# --- request models --------------------------------------------------------

class UpdateBody(BaseModel):
    summary: str | None = None
    description: str | None = None
    assigneeId: str | None = None
    priority: str | None = None
    labels: list[str] | None = None
    duedate: str | None = None
    status: str | None = None
    comment: str | None = None
    custom: dict[str, Any] | None = None


class CreateBody(BaseModel):
    project: str
    issuetype: str
    summary: str
    description: str | None = None
    parentRef: str | None = None
    assigneeId: str | None = None
    priority: str | None = None
    labels: list[str] | None = None
    duedate: str | None = None
    status: str | None = None
    comment: str | None = None
    custom: dict[str, Any] | None = None


# --- overlay of staged changes onto the cached tree ------------------------

def _overlay(tree: list[dict]) -> list[dict]:
    """Return a copy of the tree annotated with staged creates/updates."""
    import copy
    tree = copy.deepcopy(tree or [])

    index: dict[str, dict] = {}

    def walk(nodes):
        for n in nodes:
            n.setdefault("staged", None)
            index[n["key"]] = n
            walk(n["children"])

    walk(tree)

    # Mark updates.
    for op in staging.all():
        if op["kind"] == "update" and op["key"] in index:
            index[op["key"]]["staged"] = "modified"

    # Add staged creates as new nodes.
    temp_nodes: dict[str, dict] = {}
    for op in staging.all():
        if op["kind"] != "create":
            continue
        d = op["data"]
        node = {
            "key": op["tempId"],
            "summary": d.get("summary", ""),
            "type": d.get("issuetype", ""),
            "status": d.get("status", "(new)"),
            "assignee": "(new)",
            "children": [],
            "staged": "new",
        }
        temp_nodes[op["tempId"]] = node
        index[op["tempId"]] = node

    for op in staging.all():
        if op["kind"] != "create":
            continue
        node = temp_nodes[op["tempId"]]
        ref = op["data"].get("parentRef")
        if ref and ref in index:
            index[ref]["children"].append(node)
        else:
            tree.append(node)
    return tree


# --- API routes ------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": not config.missing_config(), "missing": config.missing_config(),
            "site": config.JIRA_SITE}


@app.get("/api/tree")
def get_tree(refresh: bool = False):
    if _cache["tree"] is None or refresh:
        c = client()
        try:
            _cache["me"] = c.myself()
            _cache["tree"] = c.build_tree(config.ROOT_TYPES)
        except JiraError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    return {
        "me": (_cache["me"] or {}).get("displayName", ""),
        "tree": _overlay(_cache["tree"]),
    }


@app.get("/api/meta")
def get_meta():
    c = client()
    try:
        projects = c.projects()
        priorities = c.priorities()
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {
        "projects": projects,
        "priorities": priorities,
        "defaultProject": config.DEFAULT_PROJECT,
        "rootTypes": config.ROOT_TYPES,
    }


@app.get("/api/meta/issuetypes")
def get_issue_types(project: str):
    c = client()
    try:
        return {"issuetypes": c.issue_types_for_project(project)}
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/meta/users")
def search_users(project: str, query: str = ""):
    c = client()
    return {"users": c.search_assignable(project, query or " ")}


@app.get("/api/issue/{key}")
def get_issue(key: str):
    # Staged-new issues are not in Jira yet.
    if key.startswith("temp:"):
        for op in staging.all():
            if op.get("tempId") == key:
                return {"staged_create": op}
        raise HTTPException(status_code=404, detail="Unknown staged item")
    c = client()
    try:
        issue = c.get_issue(key)
        issue["transitions"] = c.get_transitions(key)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    issue["staged_ops"] = [
        o for o in staging.all() if o.get("key") == key
    ]
    return issue


@app.post("/api/stage/update/{key}")
def stage_update(key: str, body: UpdateBody):
    op = staging.stage_update(key, body.model_dump(exclude_none=True))
    return {"op": op, "count": len(staging.all())}


@app.post("/api/stage/create")
def stage_create(body: CreateBody):
    op = staging.stage_create(body.model_dump(exclude_none=True))
    return {"op": op, "count": len(staging.all())}


@app.get("/api/staging")
def list_staging():
    return {"ops": staging.all(), "count": len(staging.all())}


@app.delete("/api/staging/{op_id}")
def delete_staging(op_id: str):
    staging.remove(op_id)
    return {"count": len(staging.all())}


@app.delete("/api/staging")
def clear_staging():
    staging.clear()
    return {"count": 0}


@app.post("/api/push")
def push():
    c = client()
    report = staging.push(c)
    # Force a refresh on next tree fetch so new/changed items show real data.
    _cache["tree"] = None
    return report


# --- static frontend -------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
