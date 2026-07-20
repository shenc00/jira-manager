# Sprint Change Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Sprint Change" button that clones an open story and its open, overdue-or-due-today sub-tasks into a new "(Iter N)" batch with a fresh 30-day target completion date, staged (not pushed) like every other write in this app.

**Architecture:** A new `JiraClient.clone_source()` fetches the raw fields needed to clone one issue; a new `JiraClient.open_children_due()` finds eligible sub-tasks. A new `POST /api/issue/{key}/sprint-change` endpoint in `main.py` validates the story, walks eligible children, and stages creates via the existing `StagingStore.stage_create()` tempId-chaining mechanism (same one epic→story→sub-task creation already uses — nothing new to build there). A pure `fields.next_iter_title()` helper computes the title suffix. The frontend adds one button and one handler function following the exact pattern of the existing `stageIssueUpdate()`.

**Tech Stack:** FastAPI (Python) backend, vanilla JS frontend. No test framework exists in this repo (verified: no `pytest.ini`/`conftest.py`/`test_*.py` anywhere) — do not introduce one. The only pure/branchy logic (`next_iter_title`) gets an assert-based `__main__` self-check instead, matching how the rest of this codebase has zero automated tests.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-17-sprint-change-design.md` — read it before starting, it's the source of truth for behavior.
- A story or sub-task with no Target Completion Date is **excluded**, not treated as eligible.
- Target Completion Date is never copied from the source — always set to `today + 30 days` on clones.
- Everything is staged via `StagingStore`; nothing calls Jira's write API directly from the endpoint. This matches every other mutation path in the app (see `backend/main.py`'s `/api/stage/create`).
- No new pip dependencies. No new JS files. No new test framework.

---

### Task 1: `next_iter_title()` title-suffix helper

**Files:**
- Modify: `backend/fields.py` (append after line 93, the end of `due_flag()`)

**Interfaces:**
- Produces: `next_iter_title(summary: str) -> str` — importable as `fields_module.next_iter_title` from `backend/main.py` (main.py already does `from . import fields as fields_module`).

- [x] **Step 1: Add the function and a manual self-check to `backend/fields.py`**

Append this to the end of the file (after the existing `due_flag()` function, which currently ends at line 93):

```python


# --- Sprint Change title suffix --------------------------------------------

_ITER_RE = re.compile(r"^(.*?)\s*\(Iter (\d+)\)$")


def next_iter_title(summary: str) -> str:
    """Bump a trailing "(Iter N)" suffix, or append "(Iter 1)" if absent.

    "Fix login bug" -> "Fix login bug (Iter 1)"
    "Fix login bug (Iter 1)" -> "Fix login bug (Iter 2)"
    """
    summary = (summary or "").strip()
    m = _ITER_RE.match(summary)
    if m:
        base, n = m.group(1), int(m.group(2))
        return f"{base} (Iter {n + 1})"
    return f"{summary} (Iter 1)"


if __name__ == "__main__":
    assert next_iter_title("Fix login bug") == "Fix login bug (Iter 1)"
    assert next_iter_title("Fix login bug (Iter 1)") == "Fix login bug (Iter 2)"
    assert next_iter_title("Fix login bug (Iter 9)") == "Fix login bug (Iter 10)"
    assert next_iter_title("  Spaced  (Iter 3)  ") == "Spaced (Iter 4)"
    assert next_iter_title("") == " (Iter 1)"
    print("ok")
```

Also add `import re` to the top of the file, next to the existing `from datetime import date, timedelta` line (line 9):

```python
import re
from datetime import date, timedelta
```

- [x] **Step 2: Run the self-check**

Run: `python backend/fields.py`
Expected output: `ok`

(`fields.py` has no relative imports, so it runs standalone.)

- [x] **Step 3: Commit**

```bash
git add backend/fields.py
git commit -m "feat: add next_iter_title() helper for Sprint Change title suffixes"
```

---

### Task 2: `JiraClient.clone_source()` and `JiraClient.open_children_due()`

**Files:**
- Modify: `backend/jira_client.py` (insert two new methods between line 464 `        }` [end of `get_issue`] and line 465 `    def get_labels(self) -> list[str]:`)

**Interfaces:**
- Consumes: `fields_mod.CRITICAL_IDS`, `fields_mod.TARGET_COMPLETION_FIELD`, `fields_mod.to_date()` (all already defined in `backend/fields.py`), `self._is_done()`, `self.search()`, `self._request()` (all already defined in this class).
- Produces:
  - `clone_source(key: str) -> dict` with keys: `key, summary, description, issuetype, subtask, statusCategory, project, parentKey, assigneeId, priority, labels, critical, targetCompletion`. `critical` is `dict[field_id, raw_value]` for every `CRITICAL_IDS` entry **except** `TARGET_COMPLETION_FIELD`, omitting any that are empty. `targetCompletion` is the raw (unformatted) value of the Target Completion Date field, or `None`.
  - `open_children_due(parent_key: str, on_or_before: date) -> list[str]` — keys of `parent_key`'s open sub-tasks whose Target Completion Date is set and `<= on_or_before`.
  - Both are consumed by `backend/main.py` in Task 3.

- [x] **Step 1: Add the two methods to `backend/jira_client.py`**

Insert immediately after line 464 (`        }`, the closing of `get_issue`'s return dict) and before line 465 (`    def get_labels(self) -> list[str]:`):

```python

    def clone_source(self, key: str) -> dict:
        """Fetch the fields needed to clone an issue for Sprint Change.

        Unlike ``get_issue`` (built for the UI detail panel), this returns
        raw values suited for feeding straight into ``StagingStore.stage_create``
        (e.g. ``assigneeId`` instead of a display name).
        """
        field_ids = (
            ["summary", "description", "issuetype", "status", "assignee",
             "priority", "labels", "parent", "project"]
            + fields_mod.CRITICAL_IDS
        )
        data = self._request("GET", f"/issue/{key}?fields={','.join(field_ids)}")
        f = data.get("fields", {})
        status = f.get("status") or {}
        assignee = f.get("assignee") or {}
        critical = {
            fid: f.get(fid)
            for fid in fields_mod.CRITICAL_IDS
            if fid != fields_mod.TARGET_COMPLETION_FIELD and f.get(fid)
        }
        return {
            "key": data["key"],
            "summary": f.get("summary", ""),
            "description": adf_to_text(f.get("description")),
            "issuetype": (f.get("issuetype") or {}).get("name", ""),
            "subtask": bool((f.get("issuetype") or {}).get("subtask")),
            "statusCategory": (status.get("statusCategory") or {}).get("key", ""),
            "project": (f.get("project") or {}).get("key", ""),
            "parentKey": (f.get("parent") or {}).get("key"),
            "assigneeId": assignee.get("accountId"),
            "priority": (f.get("priority") or {}).get("name", ""),
            "labels": f.get("labels", []),
            "critical": critical,
            "targetCompletion": f.get(fields_mod.TARGET_COMPLETION_FIELD),
        }

    def open_children_due(self, parent_key: str, on_or_before: date) -> list[str]:
        """Keys of ``parent_key``'s open sub-tasks due on or before a date.

        "Open" = statusCategory != Done. "Due" = Target Completion Date is
        set and <= ``on_or_before``. A sub-task with no Target Completion
        Date is excluded (nothing to compare).
        """
        issues = self.search(f'parent = "{parent_key}" ORDER BY created')
        keys: list[str] = []
        for issue in issues:
            if self._is_done(issue):
                continue
            due = fields_mod.to_date(
                issue.get("fields", {}).get(fields_mod.TARGET_COMPLETION_FIELD))
            if due is not None and due <= on_or_before:
                keys.append(issue["key"])
        return keys
```

- [x] **Step 2: Sanity-check the file still imports cleanly**

Run: `python -c "import ast; ast.parse(open('backend/jira_client.py').read())"`
Expected: no output, exit code 0 (confirms no syntax errors before wiring it up to the app).

- [x] **Step 3: Commit**

```bash
git add backend/jira_client.py
git commit -m "feat: add clone_source() and open_children_due() for Sprint Change"
```

---

### Task 3: `POST /api/issue/{key}/sprint-change` endpoint

**Files:**
- Modify: `backend/main.py`
  - Line 10: add `timedelta` to the datetime import
  - Between line 270 (`    return issue`) and line 273 (`@app.post("/api/stage/update/{key}")`): insert the new endpoint (with a blank line before and after, matching the file's existing style)

**Interfaces:**
- Consumes: `client()` (existing helper, line 49), `staging` (existing module-level `StagingStore`, line 43), `fields_module.next_iter_title`/`.to_date` (Task 1), `c.clone_source`/`c.open_children_due` (Task 2), `staging.stage_create(data: dict) -> dict` (existing, returns `{"id", "kind": "create", "tempId", "data"}`).
- Produces: `POST /api/issue/{key}/sprint-change` → `200 {"story": {"tempId", "summary"}, "subtasks": [{"tempId", "summary"}, ...], "count": int}`, or `400` with a `detail` message when the story is ineligible, or `502` on a Jira API error. Consumed by the frontend in Task 4.
- **Amended during implementation:** the original story and each cloned sub-task are also staged as a `Done` status transition via the existing `staging.stage_update(key, {"status": "Done"})`, since they're superseded by their clones. See `docs/superpowers/specs/2026-07-17-sprint-change-design.md` § Originals.

- [x] **Step 1: Update the datetime import**

In `backend/main.py`, change line 10 from:

```python
from datetime import date, datetime, timezone
```

to:

```python
from datetime import date, datetime, timedelta, timezone
```

- [x] **Step 2: Insert the endpoint**

Insert between line 270 (`    return issue`) and line 273 (`@app.post("/api/stage/update/{key}")`) — i.e. replace the blank line 271-272 gap with:

```python

@app.post("/api/issue/{key}/sprint-change")
def sprint_change(key: str):
    """Clone an open story/task and its open, due sub-tasks into a new
    "(Iter N)" batch with a fresh 30-day target completion date. Staged
    only — nothing is pushed to Jira until the user reviews and pushes."""
    c = client()
    try:
        story = c.clone_source(key)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if story["subtask"]:
        raise HTTPException(
            status_code=400,
            detail="Sprint Change only works on stories/tasks, not sub-tasks.")
    if story["statusCategory"] == "done":
        raise HTTPException(status_code=400, detail=f"{key} is already Done.")

    today = date.today()
    story_due = fields_module.to_date(story["targetCompletion"])
    if story_due is None or story_due > today:
        raise HTTPException(
            status_code=400,
            detail=f"{key} has no Target Completion Date on or before today.")

    try:
        child_keys = c.open_children_due(key, today)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    new_target = (today + timedelta(days=30)).isoformat()

    def clone_data(src: dict, parent_ref: str | None) -> dict:
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

    story_op = staging.stage_create(clone_data(story, story.get("parentKey")))
    subtasks: list[dict] = []
    for child_key in child_keys:
        try:
            sub = c.clone_source(child_key)
        except JiraError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        op = staging.stage_create(clone_data(sub, story_op["tempId"]))
        subtasks.append({"tempId": op["tempId"], "summary": sub["summary"]})

    return {
        "story": {"tempId": story_op["tempId"], "summary": story["summary"]},
        "subtasks": subtasks,
        "count": len(staging.all()),
    }

```

- [x] **Step 3: Sanity-check the app still imports**

Run: `python -c "from backend.main import app; print('ok')"`
Expected: `ok` (confirms no syntax/import errors; this does not require Jira credentials since it only imports the module, it doesn't call `client()`).

- [x] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat: add POST /api/issue/{key}/sprint-change endpoint"
```

---

### Task 4: Frontend button + handler

**Files:**
- Modify: `frontend/app.js`
  - Inside `renderIssueDetail()`: before the `$("#detail").innerHTML = ...` template literal (currently starting at line 361), compute a `sprintChangeButton` string; insert it into the `.detail-actions` block (currently lines 387-390)
  - After `stageIssueUpdate()` (currently ends line 608): add `sprintChange()`
  - In the `window.*` export block (currently lines 610-612): add `window.sprintChange = sprintChange;`

**Interfaces:**
- Consumes: `api()` (existing fetch wrapper, line 18), `toast()` (line 90), `refreshStageCount()` (line 928), `loadTree()` (existing, called the same way by `stageIssueUpdate` at line 606), `issue.type`/`issue.key` (existing fields already used elsewhere in `renderIssueDetail`).
- Produces: `sprintChange(key: string)`, exposed as `window.sprintChange` so the inline `onclick` handler can call it (matching how `stageIssueUpdate` and `selectItem` are already exposed).

- [x] **Step 1: Add the button to `renderIssueDetail()`**

In `frontend/app.js`, find this block (currently lines 359-361):

```javascript
  _origLabels = issue.labels || [];

  $("#detail").innerHTML = `
```

Change it to:

```javascript
  _origLabels = issue.labels || [];

  const sprintChangeButton = ["Epic", "Sub-task", "Subtask"].includes(issue.type)
    ? ""
    : `<button onclick="sprintChange('${issue.key}')" title="Clone this story and its open, due sub-tasks into a new (Iter N) batch">🔁 Sprint Change</button>`;

  $("#detail").innerHTML = `
```

Then find the `.detail-actions` block (currently lines 387-390):

```javascript
    <div class="detail-actions">
      <button class="primary" onclick="stageIssueUpdate('${issue.key}', '${issue.project}')">Stage changes</button>
      <button onclick="selectItem('${issue.key}')">Reset</button>
    </div>`;
```

Change it to:

```javascript
    <div class="detail-actions">
      <button class="primary" onclick="stageIssueUpdate('${issue.key}', '${issue.project}')">Stage changes</button>
      <button onclick="selectItem('${issue.key}')">Reset</button>
      ${sprintChangeButton}
    </div>`;
```

- [x] **Step 2: Add the `sprintChange()` handler**

In `frontend/app.js`, find this block (currently lines 607-611):

```javascript
  } catch (e) { toast(e.message, "error"); }
}

window.stageIssueUpdate = stageIssueUpdate;
window.removeStaged = removeStaged;
window.selectItem = selectItem;
```

Change it to:

```javascript
  } catch (e) { toast(e.message, "error"); }
}

async function sprintChange(key) {
  try {
    const res = await api(`/api/issue/${encodeURIComponent(key)}/sprint-change`, {
      method: "POST",
    });
    toast(`Staged: ${res.story.summary} + ${res.subtasks.length} sub-task(s).`, "success");
    refreshStageCount();
    loadTree();
  } catch (e) { toast(e.message, "error"); }
}

window.stageIssueUpdate = stageIssueUpdate;
window.removeStaged = removeStaged;
window.selectItem = selectItem;
window.sprintChange = sprintChange;
```

- [x] **Step 3: Commit**

```bash
git add frontend/app.js
git commit -m "feat: add Sprint Change button to the issue detail pane"
```

---

### Task 5: Technical validation (no live Jira on this machine)

This machine has no Jira connectivity, so Steps 1-7 of the original manual
click-through below **could not run**. Substituted with static/technical
validation of every file touched:

- [x] `python backend/fields.py` → `ok` (self-check assertions pass)
- [x] `python -c "import ast; ast.parse(open('backend/jira_client.py').read())"` → no output, exit 0
- [x] `python -c "from backend.main import app; print('ok')"` → `ok`
- [x] `node --check frontend/app.js` → exit 0

No code changes were required by validation, so nothing to commit here —
Tasks 1-4 already committed the implementation.

**Verified 2026-07-20** against live Jira (via `curl` against the running
API rather than the browser — equivalent coverage, faster to run):

- [x] **Step 1: Start the app** — `python run.py`, server started on
  `http://127.0.0.1:8123`.
- [x] **Step 2: Pick a real test story** — `ISC-2570` (Story, overdue target
  completion `2025-12-31`), with sub-task `ISC-4650` (overdue target
  completion `2026-07-17`).
- [x] **Step 3: Click Sprint Change and verify the response** —
  `POST /api/issue/ISC-2570/sprint-change` → `{"story": {...}, "subtasks": [{...}], "count": 4}`.
  Matches: 1 qualifying sub-task cloned, 4 total ops (2 creates + 2 Done updates).
- [x] **Step 4: Verify the staged tree** — `GET /api/staging` showed the
  story create (`(Iter 1)` suffix), the sub-task create chained to the
  story's `tempId` via `parentRef`, and Done updates on both originals
  (`ISC-2570`, `ISC-4650`).
- [x] **Step 5: Verify field copy** — clone carried `project`, `issuetype`,
  `description`, `assigneeId`, `priority`, `labels`; `parentRef` pointed at
  the original epic `ISC-205`; `targetCompletion` was `2026-08-19`
  (today + 30 days, not copied from the source). Matches spec.
- [x] **Step 5b (added during this verification pass): direct sub-task
  clone** — `POST /api/issue/ISC-4650/sprint-change` (a sub-task, selected
  directly rather than via its parent story) → `{"story": {...}, "subtasks": [], "count": 2}`.
  Clone's `parentRef` stayed on the real parent `ISC-2570` (not a new
  clone); no child lookup attempted. This exercises the fix in
  `0a98fcc` (sub-tasks were previously hard-rejected with a 400).
- [x] **Step 6: Verify an ineligible issue is rejected** —
  `POST /api/issue/ISC-247/sprint-change` (Epic, no Target Completion Date)
  → `400 {"detail": "ISC-247 has no Target Completion Date on or before today."}`,
  staging count unchanged (0).
- [x] **Step 7: Clean up the test staging** — `DELETE /api/staging` after
  each test; final `GET /api/staging` confirmed `{"ops": [], "count": 0}`.
  Nothing was pushed to Jira at any point.
- [x] **Step 8: Final commit** — sub-task fix committed as `0a98fcc`
  (`fix: allow Sprint Change on sub-tasks directly`) and pushed before this
  verification pass; this doc update has no separate code change to commit.

---

### Task 6: Bulk "Sprint Change all" button (2026-07-20 scope change)

User feedback after Task 5 verification: the button should be a single
global action, not a per-issue click — one click moves every qualifying
story (and, for each, all of its open sub-tasks regardless of their own due
date, not just due-today-or-earlier ones). The per-issue button stays for
one-off use.

**Files changed:**
- `backend/jira_client.py`: `open_children_due(parent_key, on_or_before)` →
  `open_children(parent_key)` (drops the due-date filter — every open
  sub-task under a qualifying story now moves with it). Added
  `sprint_change_candidates(assignee=None)`: JQL-searches stories/tasks
  (Epic and Sub-task excluded) assigned to or reported by the user, open,
  then filters client-side to Target Completion Date `<= today` (reusing
  `fields_mod.to_date`, same as the single-issue path — avoided a custom-field
  JQL date comparison since there was no existing precedent for it in this
  codebase).
- `backend/main.py`: extracted the clone/stage logic from `sprint_change()`
  into `_run_sprint_change(c, key)` + `_sprint_change_clone_data()`, reused
  by both the existing `POST /api/issue/{key}/sprint-change` and the new
  `POST /api/sprint-change/bulk?email=` (email optional, matches the
  tree's "view user" selection). Bulk runs every candidate through the same
  eligibility/clone/stage path; per-candidate failures land in `errors`
  instead of aborting the whole batch.
- `frontend/index.html`: new `🔁 Sprint Change all` button in the header
  toolbar, next to `Cancel stale on-hold`.
- `frontend/app.js`: `sprintChangeBulk()` posts to the bulk endpoint,
  toasts staged story/sub-task counts and any skipped keys, then
  `refreshStageCount()` + `loadTree()` — same pattern as every other
  write action here.
- `docs/superpowers/specs/2026-07-17-sprint-change-design.md`: updated
  Trigger & scope, Eligibility, API, and Frontend sections; removed "Bulk /
  multi-story sprint change" from Out of scope.

**Verified 2026-07-20** against live Jira (same curl-against-running-server
approach as Task 5):

- [x] Restarted the server to pick up the new code; confirmed
  `GET /api/staging` → `{"ops": [], "count": 0}` before testing.
- [x] `POST /api/sprint-change/bulk` → 5 qualifying stories
  (`ISC-4672`, `ISC-4669`, `ISC-4140`, `ISC-4138`, `ISC-2570`), 6 sub-tasks
  cloned across them, `errors: []`, `count: 22`. Verified the math:
  5 stories + 6 sub-tasks = 11 creates, + 11 matching Done updates on the
  originals = 22 total ops.
- [x] Confirmed the relaxed sub-task rule: `ISC-4138`'s sub-task `ISC-4541`
  (status "New", not overdue) and `ISC-4140`'s sub-task `ISC-4141` (status
  "On Hold") were both pulled in — neither has/needs a due date on or
  before today, only "open" (not Done) matters now.
- [x] `DELETE /api/staging` → cleared the 22 test ops.
- [x] Regression-checked the per-issue endpoint still works after the
  refactor: `POST /api/issue/ISC-4650/sprint-change` (direct sub-task) →
  `{"story": {...}, "subtasks": [], "count": 2}`, same as Task 5's Step 5b.
- [x] `DELETE /api/staging` → confirmed `{"count": 0}` again. Server
  stopped. Nothing pushed to Jira at any point.

---

## After all tasks

Push the branch:

```bash
git push
```
