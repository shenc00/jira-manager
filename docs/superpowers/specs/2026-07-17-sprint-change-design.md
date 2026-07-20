# Sprint Change button — design

## Problem

An open story slips past its sub-tasks' target completion dates. Instead of
editing dates by hand, the user wants a one-click way to clone the story and
its overdue-or-due-today open sub-tasks into a new "next iteration" batch,
with a fresh 30-day target completion date, leaving the originals untouched.

## Trigger & scope

Two entry points, sharing the same eligibility rules and clone/stage logic:

- **Per-issue**: `🔁 Sprint Change` button in the issue detail pane's
  `.detail-actions` (same spot as the existing `Stage changes` button),
  shown when the selected issue's type is not an Epic. Available on
  stories/tasks and sub-tasks alike. Operates only on the selected issue.
- **Bulk**: `🔁 Sprint Change all` button in the header toolbar (next to
  `Cancel stale on-hold`). One click, no picker, no confirmation dialog —
  finds every qualifying story/task currently in view (respects the
  `View user by email` selection, same as the tree) and runs Sprint Change
  on each. Safe to fire-and-forget because everything lands in staging only,
  same safety net as every other write path here (reviewable/discardable
  from Review changes until pushed).

## Eligibility (server-validated on click)

- Target issue (selected issue for the per-issue button; each candidate
  story/task for the bulk button): must have `statusCategory != Done`, must
  not have status On Hold (`config.ONHOLD_STATUS`), and must have a Target
  Completion Date set and `<= today`. Any failure returns 400 with a message
  (per-issue) or is skipped and reported in `errors` (bulk); nothing is
  staged for that issue.
- Bulk candidates are restricted to stories/tasks (Epic and Sub-task
  excluded) assigned to or reported by the user being viewed — a sub-task is
  never itself a bulk root, only ever pulled in as a child of a qualifying
  story.
- If the target issue is a story/task (not a sub-task), **all of its open,
  non-On-Hold** (`statusCategory != Done` and `status != On Hold`) **sub-tasks
  are also cloned, regardless of their own Target Completion Date.** If the
  target issue is itself a sub-task (per-issue button only), only it is
  cloned — no child lookup.
- **The story/task itself still needs a Target Completion Date `<= today`**
  to qualify — only the sub-task-under-a-qualifying-story rule dropped the
  date requirement.

## Cloning

For the story and each qualifying sub-task, independently:

- **Title**: if the summary ends with `(Iter N)`, strip it and use `N+1`;
  otherwise append `(Iter 1)`.
- **Copied as-is**: description, assignee, priority, labels, issue type,
  project, the other critical date fields (Start date, Development End Date,
  UAT Start/End Date), and the parent link — the story clone links to the
  original story's epic (if any); each sub-task clone links to the *new*
  story clone.
- **Not copied**: Target Completion Date (see below), comments, attachments,
  time tracking, status/workflow state (new items get the issue type's
  default create status), reporter (Jira sets it from the API token, as with
  every other create in this app).
- **Target Completion Date**: not copied — set to `today + 30 days` on every
  clone (story and sub-tasks alike).

New items are staged via the existing `StagingStore.stage_create()` /
tempId-chaining mechanism (the same one epic→story→sub-task creation already
uses) — nothing touches Jira until the user reviews and pushes, matching
every other write path in this app.

## Originals

The story and each cloned sub-task are superseded by their `(Iter N)` clone,
so both are staged as `status: Done` with `targetCompletion` set to today and
a comment `Incomplete, move to next sprint (Iter N)` (N = that item's own new
iteration number, via the existing `StagingStore.stage_update()` mechanism —
the same one the manual Status dropdown, date fields, and comment box already
use). This is a *staged* update like everything else here: nothing changes in
Jira until the user reviews and pushes, and it can be discarded from the
Review changes modal.

## API

`POST /api/issue/{key}/sprint-change`

Response: `{"story": {"tempId", "key", "summary"}, "subtasks": [...], "count"}`
(count = total staged ops, for the header badge; includes the two clone
creates plus the Done updates on the originals). 400 on ineligibility.

`POST /api/sprint-change/bulk?email=` (email optional, matches the tree's
"view user" selection)

Response: `{"stories": [{"key", "story": {...}, "subtasks": [...]}, ...],
"errors": [{"key", "detail"}, ...], "count"}` — one `stories` entry per
successfully-staged story, one `errors` entry per candidate that failed
(e.g. raced to Done between the candidate scan and staging). Never a 400
itself — an empty `stories` list with no candidates is a normal response.

## Frontend

- Per-issue button `onclick` posts to `/api/issue/{key}/sprint-change`.
  Success: toast `Staged: <story summary> + N sub-task(s). Originals staged
  as Done.`, then `refreshStageCount()` + `loadTree()` (same pattern as
  `stageIssueUpdate`). Failure: toast the error message, no state change.
- Bulk button `onclick` posts to `/api/sprint-change/bulk`. Success: toast
  the story/sub-task counts staged; a second toast lists any skipped keys
  from `errors`. No candidates: toast "No open stories/tasks are due for a
  Sprint Change." Same `refreshStageCount()` + `loadTree()` follow-up.

## Out of scope

- Jira's native "Components" field (not currently modeled anywhere in this
  app) — "all components" in the request was clarified to mean "all fields
  the app already models," not that field.
- Any field change to the original story/sub-tasks beyond the Done status
  transition described above (no summary/description/date edits, etc.).
