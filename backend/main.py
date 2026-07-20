"""FastAPI application: serves the browser UI and the JSON API.

The tree is cached in memory after each fetch so that staged (not-yet-pushed)
changes can be overlaid without re-hitting Jira on every render.
"""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from . import fields as fields_module
from .jira_client import JiraError, from_config
from .local_fields import LocalFieldsStore
from .staging import StagingStore

# The Monthly Report needs python-pptx. If it isn't installed, the rest of the
# app (tree, edit, create, push) must still work — reports just report an error.
try:
    from . import report as report_module
except ImportError:
    report_module = None

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Jira Manager")
# Allow the UI to probe /api/health on sibling ports (different port = different
# origin) when it needs to locate a server that moved. Localhost-only tool.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
staging = StagingStore(config.STAGING_FILE)
local_fields = LocalFieldsStore(config.LOCAL_FIELDS_FILE)

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
    originalEstimate: str | None = None
    remainingEstimate: str | None = None
    componentId: str | None = None
    componentName: str | None = None
    developerId: str | None = None
    developerName: str | None = None
    assignedGroupId: str | None = None
    assignedGroupName: str | None = None


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
    targetCompletion: str | None = None
    status: str | None = None
    comment: str | None = None
    custom: dict[str, Any] | None = None
    epicColor: str | None = None
    componentId: str | None = None
    componentName: str | None = None
    developerId: str | None = None
    developerName: str | None = None
    assignedGroupId: str | None = None
    assignedGroupName: str | None = None


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
            "component": d.get("componentName"),
            "developer": d.get("developerName"),
            "assignedGroup": d.get("assignedGroupName"),
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


def _overlay_local_fields(tree: list[dict]) -> None:
    """Annotate real (non-staged) nodes with Component/Developer/Assigned
    Group from the local store, in place, so the tree can search/filter/
    display them. Staged-new nodes already carry their values from _overlay()."""
    for n in tree:
        if not n["key"].startswith("temp:"):
            lf = local_fields.get(n["key"])
            n["component"] = (lf.get("component") or {}).get("name")
            n["developer"] = (lf.get("developer") or {}).get("displayName")
            n["assignedGroup"] = (lf.get("assignedGroup") or {}).get("name")
        _overlay_local_fields(n["children"])


# --- API routes ------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": not config.missing_config(), "missing": config.missing_config(),
            "site": config.JIRA_SITE}


def _resolve_view(c, email: str | None) -> dict | None:
    """Resolve an email to a user to view, or None for the current user."""
    if not email or not email.strip():
        return None
    user = c.resolve_user(email)
    if not user:
        raise HTTPException(status_code=404, detail=f"No Jira user found for '{email}'.")
    return user


@app.get("/api/tree")
def get_tree(refresh: bool = False, show_completed: bool = False,
             email: str | None = None):
    c = client()
    try:
        view = _resolve_view(c, email)
        account = view["accountId"] if view else None
        is_self = account is None
        hide_done = config.HIDE_DONE and not show_completed
        key = (account or "me", hide_done)
        if _cache["tree"] is None or refresh or _cache.get("key") != key:
            _cache["me"] = c.myself()
            _cache["tree"] = c.build_tree(
                config.ROOT_TYPES, hide_done=hide_done, assignee=account)
            _cache["key"] = key
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    # Only overlay local staged changes when looking at your own tree.
    import copy
    tree = _overlay(_cache["tree"]) if is_self else copy.deepcopy(_cache["tree"] or [])
    _overlay_local_fields(tree)
    return {
        "me": (_cache["me"] or {}).get("displayName", ""),
        "viewing": view["displayName"] if view else (_cache["me"] or {}).get("displayName", ""),
        "viewingEmail": (view or {}).get("email", ""),
        "isSelf": is_self,
        "hideDone": hide_done,
        "tree": tree,
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


@app.get("/api/meta/components")
def get_components(project: str):
    c = client()
    return {"components": c.project_components(project)}


@app.get("/api/meta/groups")
def get_groups(query: str = ""):
    c = client()
    return {"groups": c.search_groups(query)}


@app.get("/api/meta/createfields")
def get_create_fields(project: str, issuetype: str):
    """Which critical date fields can be set when creating this issue type."""
    c = client()
    try:
        ids = c.createmeta_field_ids(project, issuetype)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {
        # Target Completion Date has its own dedicated input on the create
        # form, so leave it out of the dynamic list to avoid showing it twice.
        "critical": [
            f for f in fields_module.CRITICAL_FIELDS
            if f["id"] in ids and f["id"] != fields_module.TARGET_COMPLETION_FIELD
        ],
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
    lf = local_fields.get(key)
    issue["component"] = lf.get("component")
    issue["developer"] = lf.get("developer")
    issue["assignedGroup"] = lf.get("assignedGroup")
    return issue


def _validate_local_fields(c, project: str, data: dict) -> None:
    """Referential-integrity check: a picked Component/Developer/Assigned
    Group must still exist in Jira's live master list at staging time."""
    component_id = data.get("componentId")
    if component_id:
        comps = c.project_components(project)
        if not any(x["id"] == component_id for x in comps):
            raise HTTPException(
                status_code=422,
                detail=f"'{data.get('componentName') or component_id}' is not "
                       f"a valid component for project {project}.")

    developer_id = data.get("developerId")
    if developer_id and not c.check_assignable(project, developer_id):
        raise HTTPException(
            status_code=422,
            detail=f"'{data.get('developerName') or developer_id}' is not an "
                   f"approved developer for project {project}.")

    group_id = data.get("assignedGroupId")
    if group_id:
        groups = c.search_groups(data.get("assignedGroupName", ""))
        if not any(g["groupId"] == group_id for g in groups):
            raise HTTPException(
                status_code=422,
                detail=f"'{data.get('assignedGroupName') or group_id}' is not "
                       f"a valid assignment group.")


def _sprint_change_clone_data(src: dict, parent_ref: str | None, new_target: str) -> dict:
    data: dict[str, Any] = {
        "project": src["project"],
        "issuetype": src["issuetype"],
        "summary": fields_module.next_iter_title(src["summary"]),
        "targetCompletion": new_target,
    }
    if src.get("description"):
        data["description"] = src["description"]
    if parent_ref:
        data["parentRef"] = parent_ref
    if src.get("assigneeId"):
        data["assigneeId"] = src["assigneeId"]
    if src.get("priority"):
        data["priority"] = src["priority"]
    if src.get("labels"):
        data["labels"] = src["labels"]
    if src.get("critical"):
        data["custom"] = src["critical"]
    return data


def _run_sprint_change(c, key: str) -> dict:
    """Clone an open story/task/sub-task into a new "(Iter N)" batch with a
    fresh 30-day target completion date, and stage the original(s) as Done.
    Stories/tasks also pull in all of their open sub-tasks. Staged only —
    nothing is pushed to Jira until the user reviews and pushes. Raises
    HTTPException on ineligibility or a Jira error."""
    try:
        story = c.clone_source(key)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if story["statusCategory"] == "done":
        raise HTTPException(status_code=400, detail=f"{key} is already Done.")

    today = date.today()
    story_due = fields_module.to_date(story["targetCompletion"])
    if story_due is None or story_due > today:
        raise HTTPException(
            status_code=400,
            detail=f"{key} has no Target Completion Date on or before today.")

    if story["subtask"]:
        child_keys: list[str] = []
    else:
        try:
            child_keys = c.open_children(key)
        except JiraError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    new_target = (today + timedelta(days=30)).isoformat()

    story_op = staging.stage_create(
        _sprint_change_clone_data(story, story.get("parentKey"), new_target))
    subtasks: list[dict] = []
    for child_key in child_keys:
        try:
            sub = c.clone_source(child_key)
        except JiraError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        op = staging.stage_create(
            _sprint_change_clone_data(sub, story_op["tempId"], new_target))
        subtasks.append({"tempId": op["tempId"], "summary": sub["summary"]})

    # Originals are superseded by their clones, so stage them as Done too,
    # completed today — still staged, not pushed, like every other write here.
    closed = {"status": "Done", "targetCompletion": today.isoformat()}
    staging.stage_update(key, closed)
    for child_key in child_keys:
        staging.stage_update(child_key, closed)

    return {
        "story": {"tempId": story_op["tempId"], "summary": story["summary"]},
        "subtasks": subtasks,
    }


@app.post("/api/issue/{key}/sprint-change")
def sprint_change(key: str):
    """Sprint Change a single story/task/sub-task. See _run_sprint_change."""
    c = client()
    result = _run_sprint_change(c, key)
    result["count"] = len(staging.all())
    return result


@app.post("/api/sprint-change/bulk")
def sprint_change_bulk(email: str | None = None):
    """Sprint Change every qualifying story/task in view: open, Target
    Completion Date on or before today, not an Epic or sub-task. Each pulls
    in all of its own open sub-tasks. One click, no per-item confirmation —
    like the single-issue endpoint, everything lands in staging only, so it
    stays reviewable/discardable until the user pushes."""
    c = client()
    view = _resolve_view(c, email)
    account = view["accountId"] if view else None
    try:
        candidate_keys = c.sprint_change_candidates(account)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    stories: list[dict] = []
    errors: list[dict] = []
    for key in candidate_keys:
        try:
            stories.append({"key": key, **_run_sprint_change(c, key)})
        except HTTPException as exc:
            errors.append({"key": key, "detail": exc.detail})

    return {"stories": stories, "errors": errors, "count": len(staging.all())}


@app.post("/api/stage/update/{key}")
def stage_update(key: str, body: UpdateBody):
    c = client()
    changes = body.model_dump(exclude_none=True)
    _validate_local_fields(c, key.split("-")[0], changes)
    op = staging.stage_update(key, changes)
    return {"op": op, "count": len(staging.all())}


@app.post("/api/stage/create")
def stage_create(body: CreateBody):
    c = client()
    data = body.model_dump(exclude_none=True)
    _validate_local_fields(c, data["project"], data)
    op = staging.stage_create(data)
    return {"op": op, "count": len(staging.all())}


@app.get("/api/staging")
def list_staging():
    # Strip the (potentially large) base64 payload from attachment ops; the
    # review UI only needs the filename/ref, not the bytes.
    ops = [
        {k: v for k, v in op.items() if k != "data"} if op.get("kind") == "attachment"
        else op
        for op in staging.all()
    ]
    return {"ops": ops, "count": len(ops)}


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


def _require_report():
    if report_module is None:
        raise HTTPException(
            status_code=503,
            detail="The Monthly Report needs the python-pptx library. In "
                   "PowerShell (with the .venv active) run: "
                   "pip install -r requirements.txt",
        )


@app.get("/api/report/data")
def report_data(year: int | None = None, month: int | None = None,
                email: str | None = None):
    _require_report()
    c = client()
    y, m = _report_period(year, month)
    try:
        view = _resolve_view(c, email)
        account = view["accountId"] if view else None
        owner = view["displayName"] if view else (c.myself() or {}).get("displayName", "")
        epics = report_module.gather(c, y, m, local_fields, assignee=account)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    # strip the internal colour object before returning JSON
    for ep in epics:
        for st in ep["stories"]:
            for s in st["subs"]:
                s.pop("_color", None)
    return {"month": report_module.month_label(y, m), "year": y,
            "monthNum": m, "owner": owner, "epics": epics}


@app.get("/api/report/pptx")
def report_pptx(year: int | None = None, month: int | None = None,
                email: str | None = None):
    _require_report()
    c = client()
    y, m = _report_period(year, month)
    try:
        view = _resolve_view(c, email)
        account = view["accountId"] if view else None
        owner = view["displayName"] if view else (c.myself() or {}).get("displayName", "")
        epics = report_module.gather(c, y, m, local_fields, assignee=account)
        data = report_module.build_pptx(epics, y, m, owner=owner)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    who = (owner or "me").split()[0].lower() if owner else "me"
    fname = f"monthly-report-{y}-{m:02d}-{who}.pptx"
    return StreamingResponse(
        io.BytesIO(data),
        media_type=(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


MAX_ATTACH_BYTES = 25 * 1024 * 1024  # 25 MB client/server guard


def _attach_summary(a: dict) -> dict:
    return {
        "id": a.get("id"),
        "filename": a.get("filename", ""),
        "size": a.get("size", 0),
        "mimeType": a.get("mimeType", ""),
        "created": a.get("created", ""),
        "author": (a.get("author") or {}).get("displayName", ""),
    }


@app.post("/api/issue/{key}/attachments")
async def attach_to_issue(key: str, file: UploadFile = File(...)):
    """Attach a file to an existing Jira issue (uploaded immediately)."""
    if key.startswith("temp:"):
        raise HTTPException(
            status_code=400,
            detail="This item hasn\u2019t been created in Jira yet \u2014 it will "
                   "be attached when you push.")
    data = await file.read()
    if len(data) > MAX_ATTACH_BYTES:
        raise HTTPException(status_code=413, detail="File is too large (max 25 MB).")
    c = client()
    try:
        created = c.add_attachment(
            key, file.filename or "upload", data, file.content_type)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"attachments": [_attach_summary(a) for a in created]}


@app.get("/api/issue/attachment/{attachment_id}")
def download_attachment(attachment_id: str, name: str | None = None):
    """Proxy an attachment download \u2014 the browser isn\u2019t authenticated to
    Jira, so the bytes are fetched server-side with the API token."""
    c = client()
    try:
        content, mime = c.download_attachment(attachment_id)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    safe = (name or f"attachment-{attachment_id}").replace('"', "").replace("\n", "")
    return StreamingResponse(
        io.BytesIO(content), media_type=mime or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@app.post("/api/stage/attachment")
async def stage_attachment(ref: str = Form(...), file: UploadFile = File(...)):
    """Stage a file to be attached once a not-yet-created issue is pushed.

    ``ref`` is the staged create\u2019s tempId (or a real key).
    """
    data = await file.read()
    if len(data) > MAX_ATTACH_BYTES:
        raise HTTPException(status_code=413, detail="File is too large (max 25 MB).")
    op = staging.stage_attachment(
        ref, file.filename or "upload", file.content_type, data)
    return {"op": {"id": op["id"], "filename": op["filename"], "ref": op["ref"]},
            "count": len(staging.all())}


@app.post("/api/push")
def push():
    c = client()
    report = staging.push(c, local_fields)
    # Force a refresh on next tree fetch so new/changed items show real data.
    _cache["tree"] = None
    return report


# --- static frontend -------------------------------------------------------

@app.get("/")
def index():
    """Serve index.html with cache-busting version stamps on its assets.

    The browser aggressively caches /static/app.js and /static/style.css, so
    code changes wouldn't appear on refresh. Appending the file's mtime as a
    ?v= query forces a reload whenever the asset actually changes.
    """
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    for asset in ("app.js", "style.css"):
        try:
            ver = int((FRONTEND_DIR / asset).stat().st_mtime)
        except OSError:
            continue
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={ver}")
    return HTMLResponse(html, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    })


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
