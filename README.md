# Jira Manager

A local web app to manage the Jira items assigned to you — without opening the
Jira website. It shows your **epics and tasks** (and every **sub-task** under
them, even ones assigned to others) as a **tree**. Click any item to edit its
attributes or add a comment; create new epics / tasks / sub-tasks through a
guided wizard. Nothing touches Jira until **you review and push**.

> Built for **Jira Cloud** (`*.atlassian.net`), REST API v3.

## What it does

- 🌳 **Tree view** of your epics → tasks/stories → sub-tasks.
- ✏️ **Click to edit** — summary, description, status (via workflow
  transitions), priority, assignee, due date, labels, and comments.
- ➕ **Create** epics, tasks, and sub-tasks with full attribute forms.
- 🧭 **Guided flow** — after you create an epic you're asked *"create a task?"*;
  after a task, *"create a sub-task?"*; after each creation, *"close session
  and upload now?"*. Yes/No at every step, exactly as you wanted.
- 🗂 **Staging + review** — every edit/creation is staged locally. You review
  the full list, then **push all to Jira** in one click. Nothing is sent before
  that.

## Setup

1. **Install Python 3.10+** and the dependencies:

   ```powershell
   cd "..\jira-manager"
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. **Get a Jira API token**: https://id.atlassian.com/manage-profile/security/api-tokens
   → *Create API token* → copy it.

3. **Configure**: copy `.env.example` to `.env` and fill it in:

   ```
   JIRA_SITE=https://yourcompany.atlassian.net
   JIRA_EMAIL=you@example.com
   JIRA_API_TOKEN=<the token you copied>
   JIRA_PROJECT=PROJ          # optional default project for new items
   JIRA_ROOT_TYPES=Epic,Task,Story
   ```

4. **Run**:

   ```powershell
   python run.py
   ```

   Your browser opens at http://127.0.0.1:8000.

## How the review / push model works

- Editing an item or creating one only **stages** the change locally
  (persisted to `data/staging.json`). Staged items are tagged **EDITED** /
  **NEW** in the tree.
- Click **Review changes** to see everything pending, remove individual items,
  or **Push all to Jira**.
- On push, new issues are created **parents first** (so an epic → task →
  sub-task chain you staged together is created in the right order and linked
  correctly), then field updates, comments, and status transitions are applied.
- Anything that fails stays in staging with the error shown, so you can fix or
  remove it and push again.

## Notes & limits

- **Status changes** use Jira workflow *transitions*, so only statuses
  reachable from the current one are offered.
- **Sub-tasks require a parent**; the form enforces this.
- The hierarchy uses the modern Cloud `parent` field. If your project is an old
  company-managed one that still uses the legacy *Epic Link* field, epic→task
  links may not appear — tell the maintainer and it can be extended.
- Your `.env` and `data/*.json` are git-ignored — your token and Jira data are
  never committed.

## Project layout

```
jira-manager/
├── backend/
│   ├── config.py       # env / .env loading
│   ├── jira_client.py  # Jira Cloud REST API v3 wrapper + tree builder
│   ├── staging.py      # local staging store + push logic
│   └── main.py         # FastAPI app + JSON API + serves the frontend
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js          # tree, edit panel, create wizard, review/push
├── data/               # staging.json (git-ignored)
├── run.py              # launcher
└── requirements.txt
```
