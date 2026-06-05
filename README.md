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
  **Progress** status, the **latest 3 comments from the last 4 weeks**, and a
  **summarised story description** (epics capped to 40 words). Preview in the
  browser, **download** the `.pptx`, and optionally have it **emailed to you**
  automatically through your local Outlook.
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

There are **two ways to get the app**. Do **one** of them, then follow the
shared steps (Install Python → Install dependencies → Configure → Run).

> 🟢 **Option A (Git) is recommended** — updating later is a single command.

### Option A — Install with Git (recommended)

You do **not** need to know Git. Just follow these steps.

1. **Install Git for Windows** (one time):
   - Go to https://git-scm.com/download/win — the download starts automatically.
   - Run the installer and click **Next** through every screen (the defaults are
     fine), then **Install**.
   - To check it worked: open **PowerShell** (Start menu → type `PowerShell` →
     Enter) and type `git --version`. You should see a version number.

2. **Pick where to keep the app and download it.** In PowerShell, type these two
   lines (press Enter after each):
   ```powershell
   cd "$HOME\Documents"
   git clone https://github.com/shenc00/jira-manager.git
   ```
   This creates a folder called **`jira-manager`** inside your Documents.

3. **Go into the folder:**
   ```powershell
   cd jira-manager
   ```

4. Continue with **Install Python**, **Install dependencies**, and **Configure**
   below.

**🔄 Updating later (each time the app is improved):** open PowerShell, go to the
folder, and pull the latest version:
```powershell
cd "$HOME\Documents\jira-manager"
git pull
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
`git pull` downloads all the newest features; the last two lines refresh the
libraries in case anything changed. That's the whole update — no re-downloading.

### Option B — Install from a downloaded ZIP (no Git)

1. **Download the ZIP** from SharePoint:
   [jira-manager.zip](https://bd1.sharepoint.com/:u:/r/sites/GSCTransformationGlobalSupplyChain/Shared%20Documents/General/DOMAINS%20%26%20PROJECTS/DELIVER%20Domain/Github/jira-manager.zip?csf=1&web=1&e=GP1Zkl)
2. In File Explorer, **right-click the downloaded `jira-manager.zip` → Extract
   All…** and choose a location (e.g. your **Documents** folder). You'll get a
   `jira-manager` folder.
3. Open **PowerShell** and go into that folder, e.g.:
   ```powershell
   cd "$HOME\Documents\jira-manager"
   ```
4. Continue with **Install Python**, **Install dependencies**, and **Configure**.

**🔄 Updating later:** download the new ZIP from the same link and extract it
again (replacing the old folder). Your `.env` file (below) is separate — keep a
copy of it, or just re-enter your three values after updating. *(This manual
hassle is why Option A is recommended.)*

---

### Install Python (both options)

The app needs **Python 3.10 or newer**. Many work laptops don't have it.

1. Check first — in PowerShell type:
   ```powershell
   python --version
   ```
   If it prints `Python 3.10.x` (or higher), **skip to the next section**.
2. If you get an error, or the **Microsoft Store** pops open, install Python one
   of these two ways:

   **Easiest — straight from PowerShell (no website).** On Windows 10/11 you can
   install Python 3.13 by copy-pasting this one line:
   ```powershell
   winget install -e --id Python.Python.3.13
   ```
   Then **close and reopen PowerShell** and check `python --version`.
   *(If `winget` isn't recognised, use the website method below.)*

   **Or from the website.**
   - Go to https://www.python.org/downloads/ and download the latest Windows
     installer (3.10+).
   - Run it. On the **first screen, tick the box “Add python.exe to PATH”**
     (important!), then click **Install Now**.
   - **Close and reopen PowerShell**, then re-check with `python --version`.

### Install dependencies (both options)

All of these are typed in **Windows PowerShell** (or a similar terminal). First,
make sure you are **in the `jira-manager` folder** — that's the folder created by
Option A or B above. (`cd "..\jira-manager"` just means "change into the
jira-manager folder"; use the real path, e.g. `cd "$HOME\Documents\jira-manager"`.)

Then **copy-and-paste these three lines exactly**, one at a time, pressing Enter
after each:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

- Line 1 creates a private workspace for the app's libraries.
- Line 2 turns it on — you'll see **`(.venv)`** appear at the start of the line.
- Line 3 installs everything the app needs, **including the `truststore`
  library** that fixes the first-run security/certificate error and powers the
  automatic-port feature (see *Run the app* below).

> If line 2 fails with *“running scripts is disabled on this system”*, run this
> once, then re-run line 2:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

### Configure your Jira login (`.env` file)

1. **Get a Jira API token:** https://id.atlassian.com/manage-profile/security/api-tokens
   → **Create API token** → copy it (you only see it once).
2. In the `jira-manager` folder there's a template file named **`.env.example`**.
   **Make a copy of it and rename the copy to `.env`** — exactly `.env`, with
   nothing before the dot and no `.example` at the end.
   - Easiest way (PowerShell):
     ```powershell
     Copy-Item .env.example .env
     ```
   - Or in File Explorer: right-click `.env.example` → **Copy**, paste it in the
     same folder, then rename the copy to `.env`. *(If you can't see the
     `.example` ending, turn on **View → File name extensions** in File
     Explorer.)*
3. **Open `.env` in Notepad** (right-click `.env` → **Open with → Notepad**) and
   change just these three lines, then **save**:
   ```
   JIRA_SITE=https://bd-jira.atlassian.net
   JIRA_EMAIL=your.name@bd.com
   JIRA_API_TOKEN=<paste the token you copied>
   ```
   (Leave the other lines as they are.)

> #### 🔐 Is my Jira token safe? Will sharing the app expose it?
> **No — your token stays only on your machine.** The `.env` file that holds it
> is **never** part of the shared app:
> - The Git repository and the SharePoint ZIP contain only **`.env.example`** —
>   a blank template with placeholder text, no real token.
> - `.env` is listed in `.gitignore`, so Git refuses to upload it, and the ZIP
>   is built with `git archive` (committed files only), so it **cannot** contain
>   anyone's `.env`.
> - **Every person makes their own token and their own `.env`** locally. Never
>   email or message your token. If it's ever exposed, revoke it at the token
>   page and create a new one.

### Run the app

> [!TIP]
> ### ✨ Easiest way: double-click to start
> Once your `.env` is set up (above), you can skip all the commands: just
> **double-click `start-jira-manager.bat`** in the `jira-manager` folder. The
> **first time** it automatically creates the environment and installs the
> libraries (so you can even skip the *Install dependencies* step); after that
> it just launches the app and opens your browser.
>
> To start it from your Desktop next time, right-click `start-jira-manager.bat`
> → **Send to → Desktop (create shortcut)**, then double-click that shortcut
> whenever you want the app. *(You still need Python installed, and your `.env`
> filled in once.)*

**Or start it manually from PowerShell.** With **`(.venv)`** showing (if not,
re-run `.\.venv\Scripts\Activate.ps1`), type:

```powershell
python run.py
```

Your browser opens automatically.

- **The address is specific to *your* machine.** It's usually
  **http://127.0.0.1:8123**, but if that port is blocked or busy on your PC the
  app **automatically finds a working one** (e.g. 8200) and opens the correct
  page. The exact address is also printed in PowerShell.
- **First-run error?** If the very first page shows **“Internal Server Error”**
  or a certificate error, it almost always means the **`truststore`** library
  isn't installed yet — that library lets the app work through the corporate
  network and powers the auto-port redirect. Install it by copy-pasting this one
  line into PowerShell, then **refresh the page**:
  ```powershell
  pip install truststore
  ```
  (Running `pip install -r requirements.txt` installs it too.) If the page ever
  can't reach the server, a banner appears that finds the right port and gives
  you a link to click.
- **Page says “waiting for 127.0.0.1…” or looks blank right after starting?**
  This is normal — the browser opens a split-second before the server has
  finished starting (you'll notice it most when you **restart** the app). Just
  **refresh the page once** (press **F5** or **Ctrl+R**) and it loads fine. Give
  the black window a couple of seconds to finish starting first.
- **“python is not recognised”?** Python isn't installed or wasn't added to
  PATH — go back to **Install Python** above.

> [!IMPORTANT]
> ### ⚠️ Keep the black window open — it **is** the app
> **The web page only works while the app is running.** Whether you started it
> by **double-clicking `start-jira-manager.bat`** or from PowerShell, a black
> command window stays open — **that window is the server.** If you **close it,
> the server stops and the page goes blank / stops loading.** Minimise it
> instead of closing it.
>
> **If double-clicking the `.bat` doesn't work**, start it manually in
> PowerShell: open PowerShell, `cd` to your `jira-manager` folder, then run
> these two lines:
> ```powershell
> .\.venv\Scripts\Activate.ps1
> python run.py
> ```
> Keep that PowerShell window open while you use the app.

#### Can I just bookmark the address?

**Yes.** Bookmark the address shown in your browser (e.g.
`http://127.0.0.1:8123`). On your machine the port is normally the **same every
time**, so the bookmark keeps working.

Two things to remember:
- **Start the app first.** The page only loads while `python run.py` is running.
  So each time you log on: run `python run.py` (it also re-opens the correct page
  for you automatically), then your bookmark works too.
- **If the port ever changes** (rare — only if that port becomes blocked/busy),
  `run.py` opens the new address for you. If you open an old bookmark and the
  page loads but can't reach the server, the app **auto-detects the working
  port** and shows a banner with a link to the right address — click it and
  update your bookmark to the new one.

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
· Status · Progress · Responsible · Recent comments**. Then **Download
PowerPoint** for a single-slide `.pptx`.

- **Month selector** — defaults to the current month; use the **◀ / ▶** arrows,
  the month picker, or **This month** to view any past or future month. The
  preview and the downloaded slide both follow the selected month.
- **Status** is the RAG roll-up: *Done* (blue), *Cancelled* (grey), *Overdue*
  (red, past target), *At Risk* (amber — **only when a delay is mentioned in the
  comments**), otherwise *On Track* (green).
- **Progress** is the raw Jira workflow status (New, In Progress, Development,
  Completed, Cancelled, Validation, etc.).
- **Recent comments** shows the **latest 3 comments from the last 4 weeks** of
  each sub-task (each with author + date), so the report reflects what's
  happened this month.
- **Descriptions** are summarised; bulleted ones combine every point (not just
  the first), and epic descriptions are capped to 40 words.
- **📧 Email me a copy** — leave the checkbox ticked (in the report window) and
  clicking **Download PowerPoint** also emails the slide to you automatically
  through your **local Outlook** (no password needed). It goes to your
  `JIRA_EMAIL`, or set `JIRA_REPORT_EMAIL` in `.env` to send somewhere else.
  *(Requires the Outlook desktop app installed and signed in; if it's not
  available you still get the download, plus a note explaining why the email
  didn't send.)*

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
| `JIRA_REPORT_EMAIL` | | your `JIRA_EMAIL` | Where the Monthly Report is emailed |
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
- **`ImportError: cannot import name 'BaseModel' from 'pydantic'`** (or similar
  for another library) — a previous `pip install` was interrupted (often a
  blocked download on a corporate network), leaving a half-installed library.
  **The launcher now repairs this automatically** on the next start. If it ever
  can't, fix it manually in PowerShell (with `.venv` active):
  ```powershell
  pip install --force-reinstall --no-cache-dir -r requirements.txt
  ```
  If downloads are blocked, add `--trusted-host pypi.org --trusted-host files.pythonhosted.org`.
- **Port already in use** — run on another port: `python run.py 9000`.
- **A colleague's view is empty** — they may own only sub-tasks (under other
  people's stories) and no epics/stories of their own; their sub-tasks then show
  under *your* tree/report instead.

---

## Publishing updates (for the maintainer)

How a new version reaches everyone:

- **Git users** (Option A) get updates by running `git pull` — nothing for you
  to do beyond pushing to GitHub.
- **ZIP users** (Option B) need a refreshed `jira-manager.zip` on SharePoint.

The zip is always built with `git archive`, so it contains **only committed
code** — never your `.env`, `data/`, `.git`, or `.venv`.

### Automated: GitHub Release on every version tag

A GitHub Action (`.github/workflows/release.yml`) builds the zip and attaches it
to a GitHub Release automatically whenever you push a version tag:

```powershell
git tag v1.3.0
git push origin v1.3.0
```

The zip then appears under the repo's **Releases** page — a stable download link
you can also share.

### Refreshing the SharePoint zip

The simplest reliable method: **sync the SharePoint folder once**, then run one
command after each update. OneDrive uploads the new zip automatically.

#### One-time setup (do this once)

1. In your browser, open the SharePoint **…/DELIVER Domain/Github** folder.
2. Click **Sync** (or **Add shortcut to OneDrive**) and wait until the folder
   appears in File Explorer.
3. Copy its local path: in File Explorer open that synced **Github** folder →
   click the **address bar** → copy the full path (e.g.
   `C:\Users\10320283\BD\GSC Transformation...\DELIVER Domain\Github`). You'll
   add `\jira-manager.zip` to it below.

> **You only click "Sync" once.** After that, OneDrive's background syncing is
> automatic — you do **not** re-sync on every update.

#### Repeating workflow (each time you publish an update)

In **PowerShell**, copy-paste these (commit your changes first so the zip has
the latest code), replacing the destination with *your* synced Github path:

```powershell
cd "C:\Users\10320283\OneDrive - BD\Documents\Github\jira-manager"
git add -A
git commit -m "describe the update"
git push
.\build-release.ps1 -Destination "C:\Users\10320283\BD\...\DELIVER Domain\Github\jira-manager.zip"
```

The last line rebuilds the clean zip and drops it into the synced folder;
OneDrive replaces the shared SharePoint file by itself (wait for the file's
green check ✓). Notes:
- **No `.venv` needed** — the build only uses `git`, not Python.
- If you see *"running scripts is disabled on this system"*, run
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then re-run.
- To **test without publishing**, run `.\build-release.ps1` with no
  `-Destination` — it builds `dist\jira-manager.zip` so you can inspect it first.

#### Other options

- **Fully automated in CI (needs IT/admin).** The release workflow has an
  optional **“Upload to SharePoint”** step using the Microsoft Graph API. It
  activates once an admin creates an Azure AD app registration and adds these
  repository **secrets**: `SP_TENANT_ID`, `SP_CLIENT_ID`, `SP_CLIENT_SECRET`,
  `SP_DRIVE_ID`, `SP_ITEM_PATH`. Then every tagged release also replaces the
  SharePoint zip.
- **Manual fallback.** Run `.\build-release.ps1` (no `-Destination`) and upload
  the resulting `dist\jira-manager.zip` to SharePoint through the browser,
  choosing **Replace** when prompted.

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
│   ├── emailer.py      # email the report via local Outlook (pywin32 COM)
│   └── main.py         # FastAPI app + JSON API + serves the frontend
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js          # tree, edit panel, create wizard, report, review/push
├── data/               # staging.json, auto_cancel.log (git-ignored)
├── dist/               # built jira-manager.zip (git-ignored)
├── .github/workflows/
│   └── release.yml     # auto-builds the zip + GitHub Release on a version tag
├── build-release.ps1   # build a clean zip (and optionally publish to SharePoint)
├── start-jira-manager.bat  # one-click launcher (sets up on first run)
├── run.py              # launcher (python run.py [port])
└── requirements.txt
```
