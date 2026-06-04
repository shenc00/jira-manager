# Jira Manager

A local web app to manage the Jira items assigned to you — **as a tree, without
opening the Jira website**. View and edit epics, stories and sub-tasks; create
new ones through a guided wizard; auto-cancel stale work; and generate a
**Monthly Report as a PowerPoint slide**. Everything you change is **staged
locally and only written to Jira when you review and push**.

> Built for **Jira Cloud** (`*.atlassian.net`), REST API v3. Runs entirely on
> your own machine.

---

## Features

- 🌳 **Work tree** — your epics → stories → sub-tasks, correctly nested. Every
  sub-task assigned to you appears even when its parent epic/story belongs to
  someone else (the parent is shown as context). Type-coloured, with status.
- 👁️ **Hide completed** — finished work (Done / Completed / Cancelled) is hidden
  by default; a **Show completed** toggle reveals it.
- ⏰ **Due highlighting** — items within **3 working days** of their Target
  Completion Date are flagged amber; overdue ones red.
- ✏️ **Click to edit** — summary, description, **status** (via real workflow
  transitions), priority, **assignee** (type-ahead search), due date,
  **labels** (multi-select of existing labels), the key **dates** (Start,
  Development End, UAT Start/End, Target Completion), and **comments**.
- ➕ **Create** epics, stories and sub-tasks with full attribute forms and a
  **guided flow**: after an epic → *"create a story?"*; after a story →
  *"create a sub-task?"*; after each → *"close session and upload now?"*. New
  epics default to status **In Progress** and colour **dark_orange**.
- 🗂 **Stage → review → push** — nothing touches Jira until you click **Push**.
  New issues are created parents-first; failures stay staged with the error.
- 🧹 **Auto-cancel stale on-hold** — items in "On Hold" for more than a
  threshold (default 6 months) can be transitioned to Cancelled automatically,
  with a safety cap and an audit log.
- 📊 **Monthly Report → PowerPoint** — a one-slide table of a month's sub-tasks
  (by Target Completion Date) grouped by epic/story. **Pick any month**
  (prev/next/this-month), and each row shows a **RAG status**, the raw Jira
  **Progress** status, the **latest comment**, and a **summarised story
  description** (epics capped to 40 words). Preview in the browser, then download
  the `.pptx`.
- 👥 **View any colleague** — enter a teammate's email to see *their* tree and
  generate *their* Monthly Report (read-focused; your own staging/auto-cancel
  never touch their items).
- 🔌 **Automatic port selection** — if the default port is blocked or busy
  (varies by machine), the launcher finds a working one and opens your browser
  there; if the running page ever loses the server, a banner searches the known
  ports and gives you a working link.
- 🔒 **Local & private** — your API token lives only in `.env`; the browser
  talks to your local server only. Works behind corporate HTTPS-inspection
  proxies (trusts the OS certificate store).

---

## Setup

1. **Install Python 3.10+** and the dependencies:

   ```powershell
   cd "..\jira-manager"
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. **Get a Jira API token**: https://id.atlassian.com/manage-profile/security/api-tokens
   → *Create API token* → copy it (you only see it once).

3. **Configure**: copy `.env.example` to `.env` and fill in the first three
   values (see the full reference below):

   ```
   JIRA_SITE=https://bd-jira.atlassian.net
   JIRA_EMAIL=you@bd.com
   JIRA_API_TOKEN=<the token you copied>
   ```

4. **Run**:

   ```powershell
   python run.py
   ```

   Your browser opens at **http://127.0.0.1:8123**.

---

## Opening the app — the http://127.0.0.1:8123 connection

- The app runs a small web server **on your own machine**; you use it in a
  browser. `127.0.0.1` (aka `localhost`) means "this computer" — the connection
  never leaves your laptop and no one else on the network can reach it.
- Open **http://127.0.0.1:8123** in any browser (Chrome/Edge/Firefox).
- **Why 8123?** A port is just the numbered "door" the server listens on. Port
  8000 is blocked by policy on this machine, so the default is **8123**.
- **Auto port selection** — if 8123 is blocked or busy on a given machine, the
  launcher automatically tries a list of candidate ports and starts on the first
  that works, printing the address and opening your browser there. You can also
  force one with `python run.py 9000`. If the page is open and the server later
  moves, a banner appears that searches the known ports and links you to the
  working one to reload.
- **It only works while the server is running.** Keep the terminal window open;
  closing it (or `Ctrl+C`) stops the app. Your staged changes are safe on disk
  (`data/staging.json`) and reappear next time you start it.

---

## How to use it

When the page loads you're signed in as yourself and see **My epics & tasks**.

### Browse the tree
Expand/collapse with the ▶/▼ arrows. Each row shows the type, key, summary and
status. Rows near/over their Target Completion Date are highlighted (amber =
within 3 working days, red = overdue). Tick **Show completed** (top bar) to
include finished items.

### View & edit an item
Click any row — the right panel shows its fields. Editable fields depend on what
Jira allows for that issue type (date fields not on a screen appear read-only):

- **Summary / Description**
- **Status** — only the transitions reachable from the current status
- **Priority**, **Assignee** (type 2+ letters to search), **Due date**
- **Dates** — Start date, Development End Date, UAT Start/End, Target Completion
- **Time tracking** — Original and Remaining estimate (Jira duration format,
  e.g. `2w 3d 4h`); shown read-only if the field isn't on the issue's screen
- **Labels** — multi-select dropdown of existing labels (+ a box to add new ones)
- **Add comment**

Change what you want, then **Stage changes** — the item is tagged **EDITED** in
the tree. Nothing is sent to Jira yet.

### Create new items
Click **+ New item** → choose **Epic / Story / Sub-task** → fill the form →
**Stage**. The guided flow then offers to create the natural child (epic →
story → sub-task), each auto-linked to its parent, and finally asks whether to
**close the session and upload all changes**. New epics default to **In
Progress** status and **dark_orange** colour. Sub-tasks require a parent.

### Review & push
**Review changes** (top right, with a count badge) lists every staged
edit/creation. Remove any you don't want, then **Push all to Jira**. On push,
new issues are created **parents-first** (so an epic → story → sub-task chain
links correctly), then field updates, comments and status transitions are
applied. Anything that fails stays staged with the error shown.

> 💡 Nothing you do touches Jira until you press **Push**. Staging is your safe
> review area.

### Monthly Report (PowerPoint)
Click **📊 Monthly Report**. It collects a month's sub-tasks (those with a
Target Completion Date in the selected month) under your open epics/stories and
shows a preview table with columns **Epic · Story/Sub-task · Start · Target end
· Status · Progress · Responsible · Latest update**. Then **Download
PowerPoint** for a single-slide `.pptx`.

- **Month selector** — defaults to the current month; use the **◀ / ▶** arrows,
  the month picker, or **This month** to view any past or future month. The
  preview and the downloaded slide both follow the selected month.
- **Status** is the RAG roll-up: *Done* (blue), *Cancelled* (grey), *Overdue*
  (red, past target), *At Risk* (amber — **only when a delay is mentioned in the
  comments**), otherwise *On Track* (green).
- **Progress** is the raw Jira workflow status (New, In Progress, Development,
  Completed, Cancelled, Validation, etc.).
- **Latest update** is each sub-task's most recent comment (author + date).
- **Descriptions** are summarised; bulleted ones combine every point (not just
  the first), and epic descriptions are capped to 40 words.

### View a colleague's items
Type a teammate's email in **View user by email** → **View**. The tree and the
Monthly Report now reflect *their* work; click **← back to mine** to return.
(Your local staged changes and the on-hold auto-cancel only ever apply to your
own items, never a colleague's.)

### Auto-cancel stale on-hold (optional)
When enabled (`JIRA_AUTO_CANCEL_STALE_ONHOLD=true`), on every load the app
cancels items assigned to you that have been **On Hold** longer than
`JIRA_ONHOLD_MONTHS` (default 6). A safety cap pauses for confirmation on
unusually large batches, and every cancellation is logged to
`data/auto_cancel.log`. There's also a manual **Cancel stale on-hold** button.

---

## Configuration (`.env`)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `JIRA_SITE` | ✅ | — | Your Cloud site, e.g. `https://bd-jira.atlassian.net` |
| `JIRA_EMAIL` | ✅ | — | The email you log in to Jira with |
| `JIRA_API_TOKEN` | ✅ | — | API token from id.atlassian.com |
| `JIRA_PROJECT` | | — | Default project key for new items (e.g. `ISC`) |
| `JIRA_ROOT_TYPES` | | `Epic,Task,Story` | Issue types treated as tree roots |
| `JIRA_HIDE_DONE` | | `true` | Hide Done/Completed/Cancelled by default |
| `JIRA_AUTO_CANCEL_STALE_ONHOLD` | | `false` | Auto-cancel stale on-hold items |
| `JIRA_ONHOLD_STATUS` | | `On Hold` | The "on hold" status name |
| `JIRA_CANCEL_STATUS` | | `Cancelled` | Target status when cancelling |
| `JIRA_ONHOLD_MONTHS` | | `6` | On-hold age (months) before cancelling |
| `JIRA_AUTO_CANCEL_CAP` | | `25` | Pause for confirmation above this many |
| `JIRA_VERIFY_SSL` | | `true` | TLS verification (last-resort `false`) |
| `JIRA_CA_BUNDLE` | | — | Path to a corporate root-CA `.pem` |

---

## Sharing with another user (their own token & email)

The app has **no hard-coded account** — each person's view is just
`assignee = currentUser()` from whatever token is in their `.env`.

1. **Get the code** (`git clone` or copy the folder). The repo never contains
   anyone's token — `.env` and `data/` are git-ignored.
2. **Each person creates their OWN API token** (tokens are personal; never share).
3. **They make their own `.env`** with the same `JIRA_SITE` but their email and
   token, then `pip install -r requirements.txt` and `python run.py`.
4. Two people on one PC? Give each their own copy (or swap `.env`); run two at
   once on different ports (`python run.py 8123`, `python run.py 8124`).

Each user only ever sees and does what their Jira permissions allow.

---

## Notes & limits

- **Status changes** use Jira workflow *transitions*, so only statuses reachable
  from the current one are offered.
- **Screen-restricted fields** — some fields (epic colour, time tracking, and
  certain dates) can only be written if they're on the issue's edit screen in
  Jira. Time tracking and dates render read-only when they're not editable.
  Time tracking is written as a *separate* update so a screen restriction can't
  undo your other edits; if Jira rejects it you get a **warning** on push (not a
  failure). Epic colour is applied best-effort after creating an epic; if your
  project doesn't expose it, the epic is still created with a warning.
- **Sub-tasks require a parent** (enforced by the form).
- The hierarchy uses the modern Cloud `parent` field.
- Your `.env`, `data/staging.json` and `data/auto_cancel.log` are git-ignored —
  your token and Jira data are never committed.

## Troubleshooting

- **`Internal Server Error` / SSL `CERTIFICATE_VERIFY_FAILED`** — a corporate
  HTTPS-inspection proxy is intercepting traffic. The app already trusts the OS
  certificate store (via `truststore`), which fixes most cases. If it persists,
  point `JIRA_CA_BUNDLE` at your corporate root-CA `.pem`, or as a last resort
  set `JIRA_VERIFY_SSL=false`.
- **Port already in use** — run on another port: `python run.py 9000`.
- **A colleague's view is empty** — they may own only sub-tasks (under other
  people's stories) and no epics/stories of their own; their sub-tasks then show
  under *your* tree/report instead.

---

## Project layout

```
jira-manager/
├── backend/
│   ├── config.py       # .env loading + all settings
│   ├── jira_client.py  # Jira Cloud REST v3 wrapper, tree builder, OS-trust TLS
│   ├── fields.py       # critical date-field registry + working-day/due logic
│   ├── staging.py      # local staging store + push (parents-first, colour)
│   ├── report.py       # Monthly Report: gather data, RAG, PowerPoint render
│   └── main.py         # FastAPI app + JSON API + serves the frontend
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js          # tree, edit panel, create wizard, report, review/push
├── data/               # staging.json, auto_cancel.log (git-ignored)
├── run.py              # launcher (python run.py [port])
└── requirements.txt
```
