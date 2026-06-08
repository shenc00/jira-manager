"""Local staging area for reviewed-but-not-yet-pushed Jira changes.

Two kinds of staged operations:

* ``update`` - modify an existing issue (fields / status transition / comment).
* ``create`` - create a new issue. A create gets a client-side ``tempId``
  (e.g. ``temp:ab12``). Children can reference a parent that is either a real
  Jira key (``PROJ-1``) or another staged create's tempId, so an epic ->
  task -> sub-task chain can be staged before anything exists in Jira.

On ``push`` we create issues first (parents before children, resolving
tempIds to real keys), then apply updates, then add comments / transitions.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from . import fields as fields_mod
from .jira_client import JiraClient, text_to_adf


class StagingStore:
    def __init__(self, path: Path):
        self.path = path
        self.ops: list[dict] = []
        self._load()

    # -- persistence --------------------------------------------------------

    def _load(self) -> None:
        if self.path.exists():
            try:
                self.ops = json.loads(self.path.read_text("utf-8"))
            except (ValueError, OSError):
                self.ops = []

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.ops, indent=2), encoding="utf-8")

    # -- queries ------------------------------------------------------------

    def all(self) -> list[dict]:
        return self.ops

    def clear(self) -> None:
        self.ops = []
        self._save()

    def remove(self, op_id: str) -> None:
        self.ops = [o for o in self.ops if o["id"] != op_id]
        self._save()

    # -- staging ------------------------------------------------------------

    def stage_update(self, key: str, changes: dict) -> dict:
        """Stage an update to an existing issue.

        ``changes`` may contain: summary, description, assigneeId,
        priority, labels (list), duedate, status (target name), comment,
        and ``custom`` (dict of raw fieldId -> value).
        """
        op = {
            "id": secrets.token_hex(4),
            "kind": "update",
            "key": key,
            "changes": {k: v for k, v in changes.items() if v not in (None, "")
                        or k in ("labels", "custom")},
        }
        self.ops.append(op)
        self._save()
        return op

    def stage_create(self, data: dict) -> dict:
        """Stage creation of a new issue.

        ``data`` contains: project, issuetype (name), summary, description,
        parentRef (real key or tempId, optional), assigneeId, priority,
        labels, duedate, custom.
        """
        op = {
            "id": secrets.token_hex(4),
            "kind": "create",
            "tempId": f"temp:{secrets.token_hex(3)}",
            "data": data,
        }
        self.ops.append(op)
        self._save()
        return op

    # -- push ---------------------------------------------------------------

    def _build_fields(self, data: dict, parent_key: str | None) -> dict:
        fields: dict[str, Any] = {
            "project": {"key": data["project"]},
            "issuetype": {"name": data["issuetype"]},
            "summary": data.get("summary", ""),
        }
        if data.get("description"):
            fields["description"] = text_to_adf(data["description"])
        if parent_key:
            fields["parent"] = {"key": parent_key}
        if data.get("assigneeId"):
            fields["assignee"] = {"id": data["assigneeId"]}
        if data.get("priority"):
            fields["priority"] = {"name": data["priority"]}
        if data.get("labels"):
            fields["labels"] = data["labels"]
        for field_id, value in (data.get("custom") or {}).items():
            formatted = fields_mod.format_custom(field_id, value)
            if formatted is not None:
                fields[field_id] = formatted
        return fields

    def push(self, client: JiraClient) -> dict:
        """Apply all staged operations to Jira.

        Returns a report dict with created keys and any errors. Operations
        that succeed are removed from staging; failures remain so they can be
        retried or removed.
        """
        report = {"created": [], "updated": [], "errors": [], "warnings": []}
        temp_to_real: dict[str, str] = {}
        remaining: list[dict] = []

        creates = [o for o in self.ops if o["kind"] == "create"]
        updates = [o for o in self.ops if o["kind"] == "update"]

        # Creates: iterate until no progress, so parents (whose tempId a child
        # references) are created before their children.
        pending = list(creates)
        progress = True
        while pending and progress:
            progress = False
            still_pending = []
            for op in pending:
                data = op["data"]
                ref = data.get("parentRef")
                parent_key = ref
                if ref and ref.startswith("temp:"):
                    parent_key = temp_to_real.get(ref)
                    if parent_key is None:
                        still_pending.append(op)  # parent not created yet
                        continue
                try:
                    fields = self._build_fields(data, parent_key)
                    result = client.create_issue(fields)
                    new_key = result["key"]
                    temp_to_real[op["tempId"]] = new_key
                    report["created"].append(
                        {"tempId": op["tempId"], "key": new_key,
                         "summary": data.get("summary", "")}
                    )
                    for w in self._apply_post_create(client, new_key, data):
                        report["warnings"].append({"key": new_key, "warning": w})
                    # Best-effort epic colour: the colour field often isn't on
                    # the Epic screen, so a failure must not fail the create.
                    if data.get("epicColor"):
                        try:
                            client.update_issue(
                                new_key, {"customfield_10017": data["epicColor"]})
                        except Exception as exc:  # noqa: BLE001
                            report["warnings"].append({
                                "key": new_key,
                                "warning": f"could not set colour "
                                           f"'{data['epicColor']}': {exc}",
                            })
                    progress = True
                except Exception as exc:  # noqa: BLE001 - report, keep going
                    op["error"] = str(exc)
                    remaining.append(op)
                    report["errors"].append({"op": op["id"], "error": str(exc)})
            pending = still_pending

        # Any creates left pending have an unresolved parent (e.g. parent op
        # failed) - keep them and report.
        for op in pending:
            op["error"] = "parent issue was not created"
            remaining.append(op)
            report["errors"].append(
                {"op": op["id"], "error": "parent issue was not created"}
            )

        # Updates.
        for op in updates:
            key = op["key"]
            if key.startswith("temp:"):
                key = temp_to_real.get(key, key)
            try:
                warnings = self._apply_update(client, key, op["changes"])
                report["updated"].append(key)
                for w in warnings:
                    report["warnings"].append({"key": key, "warning": w})
            except Exception as exc:  # noqa: BLE001
                op["error"] = str(exc)
                remaining.append(op)
                report["errors"].append({"op": op["id"], "error": str(exc)})

        self.ops = remaining
        self._save()
        return report

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _apply_post_create(client: JiraClient, key: str, data: dict) -> list[str]:
        """Apply post-create steps. Returns non-fatal warnings (e.g. due date
        not on the screen) so they don't fail the whole operation."""
        warnings: list[str] = []
        # Due date goes in its own update: if the Due date field isn't on the
        # issue's screen Jira rejects it, and we don't want that to fail the
        # create that already succeeded.
        if data.get("duedate"):
            try:
                client.update_issue(key, {"duedate": data["duedate"]})
            except Exception as exc:  # noqa: BLE001
                warnings.append(
                    f"{key}: could not set due date \u2014 likely not on the "
                    f"issue's edit screen in Jira ({exc})")
        if data.get("comment"):
            client.add_comment(key, data["comment"])
        if data.get("status"):
            client.transition_issue_by_name(key, data["status"])
        return warnings

    @staticmethod
    def _apply_update(client: JiraClient, key: str, changes: dict) -> list[str]:
        """Apply an update. Returns non-fatal warnings (e.g. time tracking not
        on the screen) so they don't fail the whole operation."""
        warnings: list[str] = []
        fields: dict[str, Any] = {}
        if "summary" in changes:
            fields["summary"] = changes["summary"]
        if "description" in changes:
            fields["description"] = text_to_adf(changes["description"])
        if changes.get("assigneeId"):
            fields["assignee"] = {"id": changes["assigneeId"]}
        if changes.get("priority"):
            fields["priority"] = {"name": changes["priority"]}
        if "labels" in changes:
            fields["labels"] = changes["labels"]
        for field_id, value in (changes.get("custom") or {}).items():
            # An empty value clears the field (None), so include it explicitly.
            fields[field_id] = fields_mod.format_custom(field_id, value)
        if fields:
            client.update_issue(key, fields)

        # Due date goes in its own update: if the Due date field isn't on the
        # issue's screen Jira rejects it, and we don't want that to undo the
        # other field changes above.
        if changes.get("duedate"):
            try:
                client.update_issue(key, {"duedate": changes["duedate"]})
            except Exception as exc:  # noqa: BLE001
                warnings.append(
                    f"{key}: could not set due date \u2014 likely not on the "
                    f"issue's edit screen in Jira ({exc})")

        # Time tracking goes in its own update: if the Time Tracking field isn't
        # on the issue's screen Jira rejects it, and we don't want that to undo
        # the other field changes above.
        tt: dict[str, str] = {}
        if changes.get("originalEstimate"):
            tt["originalEstimate"] = changes["originalEstimate"]
        if changes.get("remainingEstimate"):
            tt["remainingEstimate"] = changes["remainingEstimate"]
        if tt:
            try:
                client.update_issue(key, {"timetracking": tt})
            except Exception as exc:  # noqa: BLE001
                warnings.append(
                    f"{key}: could not set time tracking — likely not on the "
                    f"issue's edit screen in Jira ({exc})")

        if changes.get("comment"):
            client.add_comment(key, changes["comment"])
        if changes.get("status"):
            client.transition_issue_by_name(key, changes["status"])
        return warnings
