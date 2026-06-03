"""FastAPI application: serves the browser UI and the JSON API.

The tree is cached in memory after each fetch so that staged (not-yet-pushed)
changes can be overlaid without re-hitting Jira on every render.
"""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from . import fields as fields_module
from . import report as report_module
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
    epicColor: str | None = None


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
def get_tree(refresh: bool = False, show_completed: bool = False):
    hide_done = config.HIDE_DONE and not show_completed
    if _cache["tree"] is None or refresh or _cache.get("hide_done") != hide_done:
        c = client()
        try:
            _cache["me"] = c.myself()
            _cache["tree"] = c.build_tree(config.ROOT_TYPES, hide_done=hide_done)
            _cache["hide_done"] = hide_done
        except JiraError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    return {
        "me": (_cache["me"] or {}).get("displayName", ""),
        "hideDone": hide_done,
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
        "autoCancelOnHold": config.AUTO_CANCEL_STALE_ONHOLD,
        "onholdMonths": config.ONHOLD_MONTHS,
        "onholdStatus": config.ONHOLD_STATUS,
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


@app.get("/api/meta/labels")
def get_labels():
    c = client()
    try:
        return {"labels": c.get_labels()}
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/meta/createfields")
def get_create_fields(project: str, issuetype: str):
    """Which critical date fields can be set when creating this issue type."""
    c = client()
    try:
        ids = c.createmeta_field_ids(project, issuetype)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {
        "critical": [f for f in fields_module.CRITICAL_FIELDS if f["id"] in ids],
    }


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


def _audit_cancel(key: str, cand: dict) -> None:
    """Append one JSON line per auto-cancellation for an audit trail."""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": "auto_cancel_stale_onhold",
        "key": key,
        "onHoldSince": cand.get("since"),
        "months": cand.get("months"),
        "summary": cand.get("summary", ""),
    }
    try:
        with open(config.AUDIT_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass


@app.post("/api/scan/onhold")
def scan_onhold(apply: bool | None = None, force: bool = False):
    """Find items in the on-hold status longer than the threshold.

    ``apply`` (defaults to the JIRA_AUTO_CANCEL_STALE_ONHOLD setting) controls
    whether matches are transitioned to Cancelled. If more than the safety cap
    would be cancelled, the scan returns ``capped: true`` without cancelling
    anything unless ``force`` is set.
    """
    c = client()
    try:
        candidates = c.find_stale_onhold(config.ONHOLD_MONTHS, config.ONHOLD_STATUS)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    do_apply = config.AUTO_CANCEL_STALE_ONHOLD if apply is None else apply
    report: dict[str, Any] = {
        "candidates": candidates,
        "cancelled": [],
        "skipped": [],
        "errors": [],
        "applied": do_apply,
        "capped": False,
        "thresholdMonths": config.ONHOLD_MONTHS,
        "onholdStatus": config.ONHOLD_STATUS,
        "cancelStatus": config.CANCEL_STATUS,
    }

    if not do_apply or not candidates:
        return report

    if len(candidates) > config.AUTO_CANCEL_CAP and not force:
        report["capped"] = True
        report["cap"] = config.AUTO_CANCEL_CAP
        return report  # require explicit confirmation before mass-cancelling

    for cand in candidates:
        key = cand["key"]
        try:
            ok = c.transition_issue_by_name(key, config.CANCEL_STATUS)
            if ok:
                report["cancelled"].append(cand)
                _audit_cancel(key, cand)
            else:
                report["skipped"].append(
                    {**cand, "reason": f"no '{config.CANCEL_STATUS}' transition available"}
                )
        except JiraError as exc:
            report["errors"].append({"key": key, "error": str(exc)})

    if report["cancelled"]:
        _cache["tree"] = None  # cancelled items leave the active tree
    return report


def _report_period(year: int | None, month: int | None) -> tuple[int, int]:
    today = date.today()
    return (year or today.year), (month or today.month)


@app.get("/api/report/data")
def report_data(year: int | None = None, month: int | None = None):
    c = client()
    y, m = _report_period(year, month)
    try:
        epics = report_module.gather(c, y, m)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    # strip the internal colour object before returning JSON
    for ep in epics:
        for st in ep["stories"]:
            for s in st["subs"]:
                s.pop("_color", None)
    return {"month": report_module.month_label(y, m), "year": y,
            "monthNum": m, "epics": epics}


@app.get("/api/report/pptx")
def report_pptx(year: int | None = None, month: int | None = None):
    c = client()
    y, m = _report_period(year, month)
    try:
        epics = report_module.gather(c, y, m)
        data = report_module.build_pptx(epics, y, m)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    fname = f"manager-update-{y}-{m:02d}.pptx"
    return StreamingResponse(
        io.BytesIO(data),
        media_type=(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


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
