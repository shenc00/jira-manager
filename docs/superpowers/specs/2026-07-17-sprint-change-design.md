# Sprint Change button — design

## Problem

An open story slips past its sub-tasks' target completion dates. Instead of
editing dates by hand, the user wants a one-click way to clone the story and
its overdue-or-due-today open sub-tasks into a new "next iteration" batch,
with a fresh 30-day target completion date, leaving the originals untouched.

## Trigger & scope

- New `🔁 Sprint Change` button in the issue detail pane's `.detail-actions`
  (same spot as the existing `Stage changes` button), shown when the selected
  issue's type is not a sub-task and not an Epic.
- Clicking it operates only on the currently selected story — no separate
  picker.

## Eligibility (server-validated on click)

- Story: must not be a sub-task type, must have `statusCategory != Done`, and
  must have a Target Completion Date set and `<= today`. Any failure returns
  400 with a message; nothing is staged.
- Sub-tasks: `parent = {story key}`, open (`statusCategory != Done`), Target
  Completion Date set and `<= today`.
- **A sub-task (or the story) with no Target Completion Date is excluded** —
  there's nothing to compare against "earlier than or including today".

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

## API

`POST /api/issue/{key}/sprint-change`

Response: `{"story": {"tempId", "key", "summary"}, "subtasks": [...], "count"}`
(count = total staged ops, for the header badge). 400 on ineligibility.

## Frontend

- Button `onclick` posts to the endpoint.
- Success: toast `Staged: <story summary> clone + N sub-task(s)`, then
  `refreshStageCount()` + `loadTree()` (same pattern as `stageIssueUpdate`).
- Failure: toast the error message, no state change.

## Out of scope

- Jira's native "Components" field (not currently modeled anywhere in this
  app) — "all components" in the request was clarified to mean "all fields
  the app already models," not that field.
- Any change to the original story/sub-tasks.
- Bulk / multi-story sprint change.
