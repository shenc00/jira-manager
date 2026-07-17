"""Local overlay for Component / Developer / Assigned Group.

Jira has no native "Developer" or "Assigned Group" field on this instance,
and Component is deliberately not written back to Jira either (see the
project's setup notes) — all three are chosen from live Jira master lists
(project components, assignable users, Jira groups) but stored only in this
app, keyed by issue key. They ride along with a staged create/update and are
committed here once that operation is pushed (or, for a create, once the real
key is known) — never sent to Jira's ``fields`` payload.
"""
from __future__ import annotations

import json
from pathlib import Path


class LocalFieldsStore:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text("utf-8"))
            except (ValueError, OSError):
                self.data = {}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def get(self, key: str) -> dict:
        return self.data.get(key, {})

    def set(self, key: str, values: dict) -> None:
        """Merge ``values`` into the record for ``key``; a None value clears
        that sub-field. Drops the record entirely once it's empty."""
        rec = dict(self.data.get(key, {}))
        for k, v in values.items():
            if v is None:
                rec.pop(k, None)
            else:
                rec[k] = v
        if rec:
            self.data[key] = rec
        else:
            self.data.pop(key, None)
        self._save()
