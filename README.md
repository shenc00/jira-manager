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
   JIRA_HIDE_DONE=true        # hide Completed/Done/Cancelled items by default
   ```

4. **Run**:

   ```powershell
   python run.py
   ```

   Your browser opens automatically. See the next section about the address.

## Opening the app — the http://127.0.0.1:8123 connection

- The app runs a small web server **on your own machine** and you use it in a
  browser. `127.0.0.1` (aka `localhost`) means "this computer" — the connection
  never leaves your laptop, and no one else on the network can reach it.
- Go to **http://127.0.0.1:8123** in any browser (Chrome/Edge/Firefox).
- **Why 8123 and not 8000?** A port is just the numbered "door" the server
  listens on. Port 8000 is blocked by policy on this machine, so we use
  **8123**. If 8123 is ever busy, pick any free number (e.g. 8200, 9000) — start
  it with `python -m uvicorn backend.main:app --port 9000` and open the matching
  `http://127.0.0.1:9000`.
- **It only works while the server is running.** Keep the terminal/command
  window open. Closing it (or pressing `Ctrl+C`) stops the app and the page will
  no longer load — your staged changes are safe on disk in `data/staging.json`
  and reappear next time you start it.
- The token lives only in your local `.env`; the browser talks to *your* local
  server, which talks to Jira. Your credentials are never sent to the browser.

## Using the app (feature walkthrough)

When the page loads you're signed in as yourself and see **My epics & tasks**.

- **Tree view** — your epics, tasks and stories with every **sub-task** nested
  underneath (sub-tasks show even when assigned to someone else). Click the
  ▶/▼ arrows to expand/collapse. Type is colour-coded; current status is shown
  on the right.
- **Show completed toggle** (top bar) — by default, finished work
  (Completed / Done / Cancelled) is hidden so you see only active items. Tick
  **Show completed** to reveal everything.
- **View & edit an item** — click any row. The right panel shows its fields:
  summary, description, **status** (only the transitions allowed from its
  current status), priority, **assignee** (type 2+ letters to search users),
  due date, labels, and existing comments. Change what you want, optionally add
  a comment, then **Stage changes**. The item is tagged **EDITED** in the tree.
- **Create new items** — click **+ New item**, choose **Epic / Task /
  Sub-task**, fill the form (project, summary, description, parent, etc.), then
  **Stage**. The new item appears in the tree tagged **NEW**.
- **Guided creation flow** — after you stage an **Epic**, you're asked
  *"Create a Task?"*; after a **Task**, *"Create a Sub-task?"*; each child is
  automatically linked to the parent you just made. After the chain ends you're
  asked *"Close session and upload all changes?"* — **Yes** pushes everything,
  **No** returns you to the tree with changes still staged.
- **Review & push** — **Review changes** (top right, with a count badge) lists
  every staged edit/creation. Remove any you don't want, then **Push all to
  Jira**. Nothing is written to Jira until you push.

> 💡 Tip: nothing you do touches Jira until you press **Push**. Staging is your
> safe review area — edit, create, and rearrange freely first.

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

## Sharing this with another user (their own token & email)

The app has **no hard-coded account** — everything personal lives in the local
`.env` file, and each person's tree is just `assignee = currentUser()` resolved
from whatever token is configured. So another teammate can use the exact same
code with their own Jira identity:

1. **Get the code.** Either copy the `jira-manager` folder to their machine, or
   if it's in a git repo, `git clone` it. (The repo never contains anyone's
   token — `.env` and `data/` are git-ignored.)
2. **Each person creates their OWN API token** at
   https://id.atlassian.com/manage-profile/security/api-tokens — tokens are
   personal and must not be shared.
3. **They make their own `.env`:**
   ```powershell
   copy .env.example .env
   ```
   then fill in **their** values:
   ```
   JIRA_SITE=https://bd-jira.atlassian.net   # same site for the same company
   JIRA_EMAIL=their.name@bd.com              # their Jira login email
   JIRA_API_TOKEN=<their own token>          # the token THEY generated
   ```
4. **Install deps and run** (`pip install -r requirements.txt`, then
   `python run.py`). The tree now shows *their* assigned epics/tasks, and any
   push is attributed to *them* in Jira.

Guidelines for sharing safely:

- **One `.env` per person, never committed.** Don't email tokens or paste them
  in chat/tickets. If a token is ever exposed, revoke it on the token page and
  generate a new one.
- **Staging is local and per-machine.** `data/staging.json` holds that user's
  un-pushed changes only; it is not shared and is git-ignored.
- **Same company site, different accounts.** Everyone at BD uses the same
  `JIRA_SITE`; only `JIRA_EMAIL` + `JIRA_API_TOKEN` differ.
- **Two people on one PC?** Give each their own copy of the folder (or swap the
  `.env`) so staging and identity don't mix. Running two at once? Use different
  ports (`--port 8123`, `--port 8124`).
- Each user only ever sees and edits what their own Jira permissions allow —
  the app can't do anything in Jira that the person couldn't do themselves.

## Notes & limits

- **Completed items are hidden by default** (Jira's "Done" status category:
  Completed / Done / Cancelled). Use the **Show completed** toggle, or set
  `JIRA_HIDE_DONE=false` in `.env` to show everything by default.
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
