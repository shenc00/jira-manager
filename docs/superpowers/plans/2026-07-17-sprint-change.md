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

- [ ] **Step 1: Add the function and a manual self-check to `backend/fields.py`**

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

- [ ] **Step 2: Run the self-check**

Run: `python backend/fields.py`
Expected output: `ok`

(`fields.py` has no relative imports, so it runs standalone.)

- [ ] **Step 3: Commit**

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

- [ ] **Step 1: Add the two methods to `backend/jira_client.py`**

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

- [ ] **Step 2: Sanity-check the file still imports cleanly**

Run: `python -c "import ast; ast.parse(open('backend/jira_client.py').read())"`
Expected: no output, exit code 0 (confirms no syntax errors before wiring it up to the app).

- [ ] **Step 3: Commit**

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

- [ ] **Step 1: Update the datetime import**

In `backend/main.py`, change line 10 from:

```python
from datetime import date, datetime, timezone
```

to:

```python
from datetime import date, datetime, timedelta, timezone
```

- [ ] **Step 2: Insert the endpoint**

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

- [ ] **Step 3: Sanity-check the app still imports**

Run: `python -c "from backend.main import app; print('ok')"`
Expected: `ok` (confirms no syntax/import errors; this does not require Jira credentials since it only imports the module, it doesn't call `client()`).

- [ ] **Step 4: Commit**

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

- [ ] **Step 1: Add the button to `renderIssueDetail()`**

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

- [ ] **Step 2: Add the `sprintChange()` handler**

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

- [ ] **Step 3: Commit**

```bash
git add frontend/app.js
git commit -m "feat: add Sprint Change button to the issue detail pane"
```

---

### Task 5: End-to-end verification against the running app

No automated UI test exists in this repo (there's no browser test runner configured), so this task is a manual click-through using the `verify` skill's approach — drive the real feature, don't just eyeball the diff. This is safe to do against real Jira: Sprint Change only **stages** creates (see Task 3) — nothing is pushed to Jira until "Review changes → push" is clicked, and staged ops can be discarded from the Review changes modal without side effects.

**Files:** none (verification only).

- [ ] **Step 1: Start the app**

Run: `python run.py` (or use the project's `run` skill if one is configured)
Expected: server starts, prints the local URL (e.g. `http://127.0.0.1:8123`).

- [ ] **Step 2: Pick a real test story**

In the browser, find (or stage a throwaway) open Story/Task with:
- statusCategory not Done
- Target Completion Date set to today or earlier
- At least one open sub-task with a Target Completion Date set to today or earlier, and at least one open sub-task with either no date or a future date (to confirm filtering works)

- [ ] **Step 3: Click Sprint Change and verify the toast**

Select the story, click `🔁 Sprint Change`.
Expected: success toast reading `Staged: <summary> + N sub-task(s).` where N matches only the qualifying sub-task(s) from Step 2 (the future-dated / undated one must NOT be counted).

- [ ] **Step 4: Verify the staged tree**

Expected in the left tree: a new `NEW`-tagged story node titled `<original summary> (Iter 1)` (or `(Iter N+1)` if the original already had a suffix), with the qualifying sub-task(s) nested under it, similarly suffixed.

- [ ] **Step 5: Open the new story clone and verify field copy**

Click the new staged story node.
Expected: description, assignee, priority, labels, and the non-target-completion critical dates (Start/Dev End/UAT) match the original; Target Completion Date is not set yet (it's applied on push, per the existing `targetCompletion` staged-create mechanism used by every other create flow in this app).

- [ ] **Step 6: Verify an ineligible story is rejected**

Select a story that's either Done or has no Target Completion Date on/before today, click `🔁 Sprint Change`.
Expected: an error toast with a clear reason, and no new staged items appear (check the `Review changes` badge count is unchanged).

- [ ] **Step 7: Clean up the test staging**

Open `Review changes`, discard the staged test clones (unless you actually want them pushed).
Expected: badge count returns to its pre-test value.

- [ ] **Step 8: Final commit (docs sync, if anything changed during verification)**

If Steps 1-7 required no code changes, there's nothing to commit here — Tasks 1-4 already committed the implementation. If verification surfaced a fix, make it, re-run the relevant step, then:

```bash
git add -A
git commit -m "fix: <describe what verification caught>"
```

---

## After all tasks

Push the branch:

```bash
git push
```
