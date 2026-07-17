"use strict";

// ---------- tiny helpers ----------
const $ = (sel) => document.querySelector(sel);
const collapsed = new Set();          // keys whose children are hidden
let selectedKey = null;
let META = { projects: [], priorities: [], defaultProject: "", rootTypes: [] };
let ALL_LABELS = [];                  // every label in Jira, for the dropdown
let _origLabels = [];                 // labels of the currently open item
let viewedEmail = null;               // null = my own items; else a colleague's
let viewingSelf = true;               // whether the current tree is mine
const EPIC_COLORS = [                 // jsw-issue-color values (no native brown)
  "dark_orange", "orange", "yellow", "dark_yellow", "green", "dark_green",
  "teal", "dark_teal", "blue", "dark_blue", "purple", "dark_purple",
  "grey", "dark_grey",
];

async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
  } catch (netErr) {
    // The server is unreachable on this port — start the port watchdog.
    onDisconnected();
    throw new Error("Lost connection to the server.");
  }
  hideConnBanner(); // a successful round-trip means we're connected
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

// ---------- connection watchdog / auto port discovery ----------
// Keep in sync with PORT_CANDIDATES in run.py
const PORT_CANDIDATES = [8123, 8200, 8456, 8765, 9000, 9123, 9456, 7123, 7777, 10123];
let _probing = false;

function showConnBanner(html) {
  const b = $("#conn-banner");
  b.innerHTML = html;
  b.classList.remove("hidden");
}
function hideConnBanner() {
  const b = $("#conn-banner");
  if (b && !b.classList.contains("hidden")) b.classList.add("hidden");
}

function fetchTimeout(url, ms) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  return fetch(url, { signal: ctrl.signal, mode: "cors" })
    .finally(() => clearTimeout(t));
}

async function probeForServer() {
  const here = location.port || "80";
  for (const p of PORT_CANDIDATES) {
    if (String(p) === String(here)) continue;
    try {
      const r = await fetchTimeout(`http://127.0.0.1:${p}/api/health`, 1200);
      if (r.ok) return `http://127.0.0.1:${p}/`;
    } catch (_) { /* try next */ }
  }
  return null;
}

async function onDisconnected() {
  if (_probing) return;
  _probing = true;
  showConnBanner("⚠ Lost connection to the server — searching for a working port…");
  const url = await probeForServer();
  if (url) {
    showConnBanner(
      `✓ Server found at <b>${url}</b> — ` +
      `<a href="${url}">click here to reload on the working port</a>.`);
  } else {
    showConnBanner(
      "⚠ Couldn't reach the server on any known port. Make sure it's running " +
      "(<code>python run.py</code>), then reload this page.");
  }
  _probing = false;
}

function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast " + kind;
  setTimeout(() => (t.className = "toast hidden"), 3500);
}

function typeClass(type) {
  const safe = (type || "").replace(/\s+/g, "-");
  return ["Epic", "Story", "Task", "Bug", "Sub-task", "Subtask"].includes(safe)
    ? "type-" + safe : "type-default";
}

// ---------- modal ----------
// When `persistent` is true the modal won't close on an outside (overlay)
// click — only its own Cancel / Save buttons can close it. Used for forms
// where an accidental click outside would discard typed-in work.
let _modalPersistent = false;
function openModal(html, persistent = false) {
  $("#modal").innerHTML = html;
  _modalPersistent = persistent;
  $("#modal-overlay").classList.remove("hidden");
}
function closeModal() { _modalPersistent = false; $("#modal-overlay").classList.add("hidden"); }
$("#modal-overlay").addEventListener("click", (e) => {
  if (e.target.id === "modal-overlay" && !_modalPersistent) closeModal();
});

// Promise-based yes/no prompt
function confirmPrompt(title, message, yesLabel = "Yes", noLabel = "No") {
  return new Promise((resolve) => {
    openModal(`
      <h3>${title}</h3>
      <p>${message}</p>
      <div class="modal-actions">
        <button id="cp-no">${noLabel}</button>
        <button id="cp-yes" class="primary">${yesLabel}</button>
      </div>`);
    $("#cp-yes").onclick = () => resolve(true);
    $("#cp-no").onclick = () => resolve(false);
  });
}

// ---------- load + render tree ----------
async function loadMeta() {
  try {
    META = await api("/api/meta");
  } catch (e) {
    // Leave whatever we had before and let the user know — an empty META is
    // the usual cause of an empty Project dropdown on the create form.
    toast("Couldn't load projects: " + e.message, "error");
  }
  try { ALL_LABELS = (await api("/api/meta/labels")).labels || []; } catch (e) { ALL_LABELS = []; }
}

async function loadTree(refresh = false) {
  $("#tree").innerHTML = `<p class="muted">Loading…</p>`;
  const showCompleted = $("#chk-completed") && $("#chk-completed").checked;
  const params = new URLSearchParams();
  if (refresh) params.set("refresh", "true");
  if (showCompleted) params.set("show_completed", "true");
  if (viewedEmail) params.set("email", viewedEmail);
  try {
    const data = await api("/api/tree" + (params.toString() ? "?" + params : ""));
    viewingSelf = data.isSelf;
    if (data.isSelf) {
      $("#who").innerHTML = data.me ? `Signed in as ${escapeHtml(data.me)}` : "";
      $("#tree-pane h2") && ($("#tree-pane h2").textContent = "My epics & tasks");
    } else {
      $("#who").innerHTML = `Viewing <b>${escapeHtml(data.viewing)}</b>'s items `
        + `<a href="#" id="back-to-me">← back to mine</a> <span class="muted">(you are ${escapeHtml(data.me)})</span>`;
      $("#tree-pane h2") && ($("#tree-pane h2").textContent = `${data.viewing}'s epics & tasks`);
      const back = $("#back-to-me");
      if (back) back.onclick = (e) => { e.preventDefault(); backToMe(); };
    }
    renderTree(data.tree);
  } catch (e) {
    $("#tree").innerHTML = `<p class="stage-error">${e.message}</p>`;
  }
  refreshStageCount();
}

function viewUser() {
  const email = ($("#view-email").value || "").trim();
  if (!email) { toast("Enter an email to view."); return; }
  viewedEmail = email;
  loadTree(true);
}

function backToMe() {
  viewedEmail = null;
  $("#view-email").value = "";
  loadTree(true);
}

// ---------- tree search / filter ----------
let searchTerm = "";   // current filter (lowercased); "" = show everything

// Does this single node match the search term?
function nodeMatches(node, term) {
  return [node.key, node.summary, node.type, node.status,
          node.component, node.developer, node.assignedGroup]
    .some((v) => (v || "").toLowerCase().includes(term));
}

// Keep any node whose own text matches, or that has a matching descendant.
// A node that matches itself keeps its full subtree; a node kept only because
// of a descendant keeps just the path to that descendant.
function pruneTree(nodes, term) {
  const out = [];
  for (const n of nodes) {
    const selfHit = nodeMatches(n, term);
    const kids = n.children && n.children.length ? pruneTree(n.children, term) : [];
    if (selfHit) out.push(n);            // keep original children intact
    else if (kids.length) out.push({ ...n, children: kids });
  }
  return out;
}

function renderTree(nodes) {
  if (!nodes || !nodes.length) {
    $("#tree").innerHTML = `<p class="muted">No epics or tasks assigned to you.</p>`;
    return;
  }
  let toRender = nodes;
  if (searchTerm) {
    toRender = pruneTree(nodes, searchTerm);
    if (!toRender.length) {
      $("#tree").innerHTML = `<p class="muted">No items match “${escapeHtml(searchTerm)}”.</p>`;
      return;
    }
  }
  const root = document.createElement("ul");
  toRender.forEach((n) => root.appendChild(renderNode(n)));
  $("#tree").innerHTML = "";
  $("#tree").appendChild(root);
}

function renderNode(node) {
  const li = document.createElement("li");
  const row = document.createElement("div");
  row.className = "node-row" + (node.key === selectedKey ? " selected" : "");

  const hasKids = node.children && node.children.length;
  // While searching, force every branch open so matches are always visible.
  const isCollapsed = !searchTerm && collapsed.has(node.key);
  if (searchTerm && nodeMatches(node, searchTerm)) row.classList.add("search-match");

  const toggle = document.createElement("span");
  toggle.className = "toggle" + (hasKids ? "" : " leaf");
  toggle.textContent = hasKids ? (isCollapsed ? "▶" : "▼") : "•";
  toggle.onclick = (e) => {
    e.stopPropagation();
    if (!hasKids) return;
    isCollapsed ? collapsed.delete(node.key) : collapsed.add(node.key);
    loadTreeFromCacheRerender();
  };

  const chip = document.createElement("span");
  chip.className = "type-chip " + typeClass(node.type);
  chip.textContent = node.type || "?";

  const key = document.createElement("span");
  key.className = "node-key";
  key.textContent = node.key.startsWith("temp:") ? "NEW" : node.key;

  const summary = document.createElement("span");
  summary.className = "node-summary";
  summary.textContent = node.summary;

  const status = document.createElement("span");
  status.className = "node-status";
  status.textContent = node.status || "";

  row.append(toggle, chip, key, summary, status);

  [["component", node.component], ["developer", node.developer], ["assignedGroup", node.assignedGroup]]
    .forEach(([kind, value]) => {
      if (!value) return;
      const tag = document.createElement("span");
      tag.className = "meta-tag meta-" + kind;
      tag.textContent = value;
      row.appendChild(tag);
    });

  // Highlight items at/over their Target Completion Date (working days).
  if (node.dueFlag) {
    row.classList.add("due-" + node.dueFlag);
    const due = document.createElement("span");
    due.className = "due-tag due-" + node.dueFlag;
    const wd = node.workingDays;
    due.textContent = node.dueFlag === "overdue"
      ? `OVERDUE ${Math.abs(wd)}wd (${node.targetCompletion})`
      : `DUE ${wd}wd (${node.targetCompletion})`;
    due.title = "Target Completion Date " + node.targetCompletion;
    row.appendChild(due);
  }

  if (node.staged) {
    const tag = document.createElement("span");
    tag.className = "staged-tag staged-" + node.staged;
    tag.textContent = node.staged === "new" ? "NEW" : "EDITED";
    row.appendChild(tag);
  }

  row.onclick = () => selectItem(node.key);
  li.appendChild(row);

  if (hasKids && !isCollapsed) {
    const ul = document.createElement("ul");
    node.children.forEach((c) => ul.appendChild(renderNode(c)));
    li.appendChild(ul);
  }
  return li;
}

// Re-render using last fetched tree without hitting Jira (for collapse toggles)
let _lastTree = null;
function loadTreeFromCacheRerender() {
  if (_lastTree) renderTree(_lastTree);
}
// wrap renderTree to remember
const _renderTree = renderTree;
renderTree = function (nodes) { _lastTree = nodes; _renderTree(nodes); };

// ---------- detail / edit ----------
async function selectItem(key) {
  selectedKey = key;
  loadTreeFromCacheRerender();
  const pane = $("#detail");
  pane.innerHTML = `<p class="muted">Loading ${key}…</p>`;
  try {
    const issue = await api("/api/issue/" + encodeURIComponent(key));
    if (issue.staged_create) renderStagedCreateDetail(issue.staged_create);
    else renderIssueDetail(issue);
  } catch (e) {
    pane.innerHTML = `<p class="stage-error">${e.message}</p>`;
  }
}

function field(label, inner) {
  return `<div class="field"><label>${label}</label>${inner}</div>`;
}

function renderStagedCreateDetail(op) {
  const d = op.data;
  $("#detail").innerHTML = `
    <div class="staged-note">This is a <b>new ${d.issuetype}</b> staged for creation.
      It will be created in Jira when you push.</div>
    <h2>${d.summary}</h2>
    <p class="muted">Project ${d.project}${d.parentRef ? " · parent " + d.parentRef : ""}</p>
    <div class="field"><label>Description</label><div>${(d.description || "—").replace(/\n/g, "<br>")}</div></div>
    <div class="detail-actions">
      <button class="danger" onclick="removeStaged('${op.id}')">Discard this new item</button>
    </div>`;
}

function renderIssueDetail(issue) {
  const transitions = issue.transitions || [];
  const statusOpts = [`<option value="">${issue.status} (no change)</option>`]
    .concat(transitions.map((t) => `<option value="${t.to}">→ ${t.to} (${t.name})</option>`))
    .join("");
  const priOpts = [`<option value="">${issue.priority || "—"} (no change)</option>`]
    .concat((META.priorities || []).map((p) => `<option value="${p.name}">${p.name}</option>`))
    .join("");

  const commentsHtml = (issue.comments || []).map((c) => `
    <div class="comment"><div class="meta">${c.author} · ${(c.created || "").slice(0,10)}</div>
    <div>${(c.body || "").replace(/\n/g, "<br>")}</div></div>`).join("") || `<p class="muted">No comments.</p>`;

  const stagedNote = (issue.staged_ops && issue.staged_ops.length)
    ? `<div class="staged-note">You have ${issue.staged_ops.length} staged change(s) on this item awaiting push.</div>` : "";

  let dueBanner = "";
  if (issue.dueFlag === "overdue")
    dueBanner = `<div class="due-banner due-overdue">⚠ Overdue: target completion was ${Math.abs(issue.workingDays)} working day(s) ago.</div>`;
  else if (issue.dueFlag === "soon")
    dueBanner = `<div class="due-banner due-soon">⏰ Due soon: ${issue.workingDays} working day(s) to target completion.</div>`;

  _origLabels = issue.labels || [];

  const sprintChangeButton = ["Epic", "Sub-task", "Subtask"].includes(issue.type)
    ? ""
    : `<button onclick="sprintChange('${issue.key}')" title="Clone this story and its open, due sub-tasks into a new (Iter N) batch, and stage the originals as Done">🔁 Sprint Change</button>`;

  $("#detail").innerHTML = `
    ${stagedNote}${dueBanner}
    <h2>${issue.summary}</h2>
    <p class="muted"><b>${issue.key}</b> · ${issue.type} · reporter ${issue.reporter}
      ${issue.parent ? " · parent " + issue.parent : ""}</p>

    ${field("Summary", `<input type="text" id="f-summary" value="${escapeAttr(issue.summary)}">`)}
    ${field("Description",
        `<textarea id="f-desc">${escapeHtml(issue.description)}</textarea>`)}
    <div class="row">
      ${field("Status", `<select id="f-status">${statusOpts}</select>`)}
      ${field("Priority", `<select id="f-priority">${priOpts}</select>`)}
    </div>
    ${field("Assignee", assigneeInput("f-assignee", issue.assignee && issue.assignee.displayName, issue.project))}
    <div class="row">
      ${field("Component", componentSelectHtml("f-component", issue.component && issue.component.name))}
      ${field("Developer", assigneeInput("f-developer", issue.developer && issue.developer.displayName, issue.project))}
    </div>
    ${field("Assigned Group", groupInput("f-group", issue.assignedGroup && issue.assignedGroup.name))}

    ${criticalFieldsHtml(issue.critical)}

    ${timeTrackingHtml(issue.timetracking)}

    ${field("Labels", labelsWidget("f-labels", issue.labels))}
    ${field("Attachments", attachmentsBlock(issue))}
    ${field("Add comment",
        `<textarea id="f-comment" placeholder="Leave blank to skip"></textarea>`)}

    <div class="comments"><label class="muted">Existing comments</label>${commentsHtml}</div>

    <div class="detail-actions">
      <button class="primary" onclick="stageIssueUpdate('${issue.key}', '${issue.project}')">Stage changes</button>
      <button onclick="selectItem('${issue.key}')">Reset</button>
      ${sprintChangeButton}
    </div>`;
  wireAssignee("f-assignee", issue.project);
  wireAssignee("f-developer", issue.project);
  wireGroup("f-group");
  loadComponentOptions("f-component", issue.project);
  wireAttachImmediate(issue.key);
}

// Render the critical date fields; disabled (read-only) when not on the
// issue's edit screen. Each input carries data-cf (field id) and data-orig.
function criticalFieldsHtml(critical) {
  if (!critical || !critical.length) return "";
  const cells = critical.map((f) => {
    const note = f.editable ? "" : ` <span class="muted">(not editable here)</span>`;
    const dis = f.editable ? "" : "disabled";
    return field(f.name + note,
      `<input type="date" id="cf-${f.id}" data-cf="${f.id}" data-orig="${f.value || ""}" value="${f.value || ""}" ${dis}>`);
  });
  let html = `<div class="section-label">Dates</div>`;
  for (let i = 0; i < cells.length; i += 2)
    html += `<div class="row">${cells[i] || ""}${cells[i + 1] || ""}</div>`;
  return html;
}

// Time tracking (original + remaining estimate). Editable per editmeta; if not
// on the issue's screen we still show the inputs but disabled, with a note.
function timeTrackingHtml(tt) {
  if (!tt) return "";
  const dis = tt.editable ? "" : "disabled";
  const note = tt.editable
    ? ""
    : ` <span class="muted">(not on this issue's screen — saving may be rejected by Jira)</span>`;
  const spent = tt.timeSpent
    ? `<div class="muted" style="font-size:11px">Logged so far: ${escapeHtml(tt.timeSpent)}</div>` : "";
  return `<div class="section-label">Time tracking${note}</div>
    <div class="row">
      ${field("Original estimate", `<input type="text" id="tt-orig" data-orig="${escapeAttr(tt.originalEstimate || "")}" value="${escapeAttr(tt.originalEstimate || "")}" placeholder="e.g. 2w 3d 4h" ${dis}>`)}
      ${field("Remaining estimate", `<input type="text" id="tt-rem" data-orig="${escapeAttr(tt.remainingEstimate || "")}" value="${escapeAttr(tt.remainingEstimate || "")}" placeholder="e.g. 1w 2d" ${dis}>`)}
    </div>
    ${spent}`;
}

function collectTimeTracking() {
  const o = document.getElementById("tt-orig");
  const r = document.getElementById("tt-rem");
  const out = {};
  if (o && !o.disabled && o.value.trim() && o.value !== o.dataset.orig)
    out.originalEstimate = o.value.trim();
  if (r && !r.disabled && r.value.trim() && r.value !== r.dataset.orig)
    out.remainingEstimate = r.value.trim();
  return out;
}

function collectCustom() {
  const out = {};
  document.querySelectorAll("#detail [data-cf]").forEach((el) => {
    if (el.disabled) return;
    if (el.value !== el.dataset.orig) out[el.dataset.cf] = el.value || "";
  });
  return Object.keys(out).length ? out : null;
}

// Labels multi-select dropdown (+ free-text box to add brand-new labels).
function labelsWidget(id, current) {
  const cur = current || [];
  const known = ALL_LABELS.slice();
  cur.forEach((l) => { if (!known.includes(l)) known.push(l); });
  known.sort((a, b) => a.localeCompare(b));
  const opts = known.map((l) =>
    `<option value="${escapeAttr(l)}" ${cur.includes(l) ? "selected" : ""}>${escapeHtml(l)}</option>`).join("");
  return `<select id="${id}" class="labels-select" multiple size="6">${opts}</select>
    <input type="text" id="${id}-new" placeholder="Add new label(s), comma separated" class="labels-new">
    <div class="muted" style="font-size:11px">Ctrl/Cmd-click to select multiple.</div>`;
}

function collectLabels(id) {
  const sel = document.getElementById(id);
  const chosen = sel ? Array.from(sel.selectedOptions).map((o) => o.value) : [];
  const raw = (document.getElementById(id + "-new") || {}).value || "";
  const extras = raw.split(",").map((s) => s.trim()).filter(Boolean);
  return Array.from(new Set([...chosen, ...extras]));
}

function escapeHtml(s) { return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function escapeAttr(s) { return escapeHtml(s).replace(/"/g,"&quot;"); }

// Assignee search widget --------------------------------------------------
// A custom searchable dropdown (native <datalist> proved unreliable across
// browsers). Typing queries Jira's assignable-users endpoint; clicking a row
// selects that user. The chosen accountId is stored on the input's dataset.
function assigneeInput(id, current, project) {
  return `<div class="assignee-wrap">
            <input type="text" id="${id}" class="assignee-input"
                   placeholder="${current ? escapeAttr("Currently: " + current) : "Search user…"}"
                   data-account="" autocomplete="off">
            <div id="${id}-menu" class="assignee-menu hidden"></div>
          </div>`;
}

function wireAssignee(id, project) {
  const input = document.getElementById(id);
  const menu = document.getElementById(id + "-menu");
  if (!input || !menu) return;
  let timer;
  let activeIdx = -1;

  function hide() { menu.classList.add("hidden"); activeIdx = -1; }
  function show() { if (menu.children.length) menu.classList.remove("hidden"); }

  function render(users) {
    input._users = users;
    if (!users.length) {
      menu.innerHTML = `<div class="assignee-empty">No matching users</div>`;
      show();
      return;
    }
    menu.innerHTML = users.map((u, i) =>
      `<div class="assignee-option" data-idx="${i}" data-account="${escapeAttr(u.accountId)}">${escapeHtml(u.displayName)}</div>`
    ).join("");
    activeIdx = -1;
    show();
  }

  function pick(user) {
    input.value = user.displayName;
    input.dataset.account = user.accountId;
    hide();
  }

  async function query(q) {
    try {
      const { users } = await api(
        `/api/meta/users?project=${encodeURIComponent(project)}&query=${encodeURIComponent(q || " ")}`);
      render(users || []);
    } catch (_) { hide(); }
  }

  input.addEventListener("focus", () => {
    // Show a default list immediately so the dropdown is obviously available.
    if (input._users && input._users.length) { show(); }
    else { query(input.value.trim()); }
  });

  input.addEventListener("input", () => {
    // Typing invalidates any previously selected account until re-picked.
    input.dataset.account = "";
    clearTimeout(timer);
    const q = input.value.trim();
    timer = setTimeout(() => query(q), 250);
  });

  input.addEventListener("keydown", (e) => {
    const opts = Array.from(menu.querySelectorAll(".assignee-option"));
    if (!opts.length || menu.classList.contains("hidden")) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIdx = Math.min(activeIdx + 1, opts.length - 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIdx = Math.max(activeIdx - 1, 0);
    } else if (e.key === "Enter") {
      if (activeIdx >= 0) { e.preventDefault(); pick(input._users[activeIdx]); return; }
    } else if (e.key === "Escape") {
      hide(); return;
    } else { return; }
    opts.forEach((o, i) => o.classList.toggle("active", i === activeIdx));
    if (opts[activeIdx]) opts[activeIdx].scrollIntoView({ block: "nearest" });
  });

  menu.addEventListener("mousedown", (e) => {
    // mousedown (not click) so it fires before the input's blur.
    const opt = e.target.closest(".assignee-option");
    if (!opt) return;
    e.preventDefault();
    pick(input._users[Number(opt.dataset.idx)]);
  });

  input.addEventListener("blur", () => setTimeout(hide, 150));
}

function resolveAssignee(id) {
  const input = document.getElementById(id);
  if (!input || !input.value.trim()) return null;
  if (input.dataset.account) return input.dataset.account;
  // Fall back to an exact display-name match if the user typed but didn't click.
  const match = (input._users || []).find((u) => u.displayName === input.value.trim());
  return match ? match.accountId : null;
}

// Developer uses the same assignable-users widget as Assignee (Jira's
// project-scoped assignable list doubles as the "approved developer" list).
// This resolves both the accountId and the display name in one call.
function resolveNamedAssignee(id) {
  const accountId = resolveAssignee(id);
  const input = document.getElementById(id);
  return { id: accountId, name: accountId && input ? input.value.trim() : null };
}

// Component select ----------------------------------------------------------
// A plain <select>, like Priority: current value shown as a "(no change)"
// placeholder, real options for the issue's project loaded asynchronously.
function componentSelectHtml(id, currentName) {
  const placeholder = currentName ? `${escapeHtml(currentName)} (no change)` : "—";
  return `<select id="${id}"><option value="">${placeholder}</option></select>`;
}

async function loadComponentOptions(selectId, project) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  try {
    const { components } = await api(`/api/meta/components?project=${encodeURIComponent(project)}`);
    const opts = (components || []).map((c) =>
      `<option value="${escapeAttr(c.id)}" data-name="${escapeAttr(c.name)}">${escapeHtml(c.name)}</option>`
    ).join("");
    sel.insertAdjacentHTML("beforeend", opts);
  } catch (e) { /* leave the placeholder-only select */ }
}

function collectComponent(selectId) {
  const sel = document.getElementById(selectId);
  if (!sel || !sel.value) return { id: null, name: null };
  const opt = sel.selectedOptions[0];
  return { id: sel.value, name: opt ? opt.dataset.name : "" };
}

// Assigned Group search widget -----------------------------------------------
// Same typeahead UX as Assignee, backed by Jira's group picker instead of
// assignable users.
function groupInput(id, current) {
  return `<div class="assignee-wrap">
            <input type="text" id="${id}" class="assignee-input"
                   placeholder="${current ? escapeAttr("Currently: " + current) : "Search group…"}"
                   data-groupid="" autocomplete="off">
            <div id="${id}-menu" class="assignee-menu hidden"></div>
          </div>`;
}

function wireGroup(id) {
  const input = document.getElementById(id);
  const menu = document.getElementById(id + "-menu");
  if (!input || !menu) return;
  let timer;
  let activeIdx = -1;

  function hide() { menu.classList.add("hidden"); activeIdx = -1; }
  function show() { if (menu.children.length) menu.classList.remove("hidden"); }

  function render(groups) {
    input._groups = groups;
    if (!groups.length) {
      menu.innerHTML = `<div class="assignee-empty">No matching groups</div>`;
      show();
      return;
    }
    menu.innerHTML = groups.map((g, i) =>
      `<div class="assignee-option" data-idx="${i}">${escapeHtml(g.name)}</div>`
    ).join("");
    activeIdx = -1;
    show();
  }

  function pick(group) {
    input.value = group.name;
    input.dataset.groupid = group.groupId;
    hide();
  }

  async function query(q) {
    try {
      const { groups } = await api(`/api/meta/groups?query=${encodeURIComponent(q || "")}`);
      render(groups || []);
    } catch (_) { hide(); }
  }

  input.addEventListener("focus", () => {
    if (input._groups && input._groups.length) { show(); }
    else { query(input.value.trim()); }
  });

  input.addEventListener("input", () => {
    input.dataset.groupid = "";
    clearTimeout(timer);
    const q = input.value.trim();
    timer = setTimeout(() => query(q), 250);
  });

  input.addEventListener("keydown", (e) => {
    const opts = Array.from(menu.querySelectorAll(".assignee-option"));
    if (!opts.length || menu.classList.contains("hidden")) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIdx = Math.min(activeIdx + 1, opts.length - 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIdx = Math.max(activeIdx - 1, 0);
    } else if (e.key === "Enter") {
      if (activeIdx >= 0) { e.preventDefault(); pick(input._groups[activeIdx]); return; }
    } else if (e.key === "Escape") {
      hide(); return;
    } else { return; }
    opts.forEach((o, i) => o.classList.toggle("active", i === activeIdx));
    if (opts[activeIdx]) opts[activeIdx].scrollIntoView({ block: "nearest" });
  });

  menu.addEventListener("mousedown", (e) => {
    const opt = e.target.closest(".assignee-option");
    if (!opt) return;
    e.preventDefault();
    pick(input._groups[Number(opt.dataset.idx)]);
  });

  input.addEventListener("blur", () => setTimeout(hide, 150));
}

function resolveGroup(id) {
  const input = document.getElementById(id);
  if (!input || !input.value.trim()) return { id: null, name: null };
  if (input.dataset.groupid) return { id: input.dataset.groupid, name: input.value.trim() };
  const match = (input._groups || []).find((g) => g.name === input.value.trim());
  return match ? { id: match.groupId, name: match.name } : { id: null, name: null };
}

// Collect edit form into a changes object
function collectChanges() {
  const labels = collectLabels("f-labels");
  const labelsChanged =
    JSON.stringify([...labels].sort()) !== JSON.stringify([..._origLabels].sort());
  const tt = collectTimeTracking();
  const component = collectComponent("f-component");
  const developer = resolveNamedAssignee("f-developer");
  const group = resolveGroup("f-group");
  return {
    summary: document.getElementById("f-summary").value.trim() || null,
    description: document.getElementById("f-desc").value,
    status: document.getElementById("f-status").value || null,
    priority: document.getElementById("f-priority").value || null,
    labels: labelsChanged ? labels : null,
    comment: document.getElementById("f-comment").value.trim() || null,
    assigneeId: resolveAssignee("f-assignee"),
    custom: collectCustom(),
    originalEstimate: tt.originalEstimate || null,
    remainingEstimate: tt.remainingEstimate || null,
    componentId: component.id,
    componentName: component.name,
    developerId: developer.id,
    developerName: developer.name,
    assignedGroupId: group.id,
    assignedGroupName: group.name,
  };
}

async function stageIssueUpdate(key) {
  const changes = collectChanges();
  Object.keys(changes).forEach((k) => changes[k] == null && delete changes[k]);
  if (!Object.keys(changes).length) { toast("Nothing to stage."); return; }
  try {
    const { count } = await api("/api/stage/update/" + encodeURIComponent(key), {
      method: "POST", body: JSON.stringify(changes),
    });
    toast(`Staged. ${count} change(s) pending review.`, "success");
    refreshStageCount();
    loadTree(); // overlay marks the item as edited
  } catch (e) { toast(e.message, "error"); }
}

async function sprintChange(key) {
  try {
    const res = await api(`/api/issue/${encodeURIComponent(key)}/sprint-change`, {
      method: "POST",
    });
    toast(`Staged: ${res.story.summary} + ${res.subtasks.length} sub-task(s). Originals staged as Done.`, "success");
    refreshStageCount();
    loadTree();
  } catch (e) { toast(e.message, "error"); }
}

window.stageIssueUpdate = stageIssueUpdate;
window.removeStaged = removeStaged;
window.selectItem = selectItem;
window.sprintChange = sprintChange;

// ---------- create wizard ----------
function newItemFlow() {
  openModal(`
    <h3>What do you want to create?</h3>
    <div class="choice-grid">
      <div class="choice" data-cat="Epic"><div class="big">🏔️</div><div>Epic</div></div>
      <div class="choice" data-cat="Story"><div class="big">📘</div><div>Story</div></div>
      <div class="choice" data-cat="Sub-task"><div class="big">↳</div><div>Sub-task</div></div>
    </div>
    <div class="modal-actions"><button onclick="closeModalBtn()">Cancel</button></div>`);
  document.querySelectorAll(".choice").forEach((c) => {
    c.onclick = () => openCreateForm(c.dataset.cat, null);
  });
}
window.closeModalBtn = closeModal;

async function openCreateForm(category, parentRef) {
  // The Project list comes from /api/meta, loaded at startup. If that load
  // failed (transient Jira/network error), META.projects is empty and the
  // dropdown would have nothing to pick — retry the load before rendering.
  if (!META.projects || !META.projects.length) {
    await loadMeta();
  }
  const projects = META.projects || [];
  if (!projects.length) {
    toast("No projects available — check your Jira connection and config.", "error");
    return;
  }
  const defProj = META.defaultProject || (projects[0] && projects[0].key) || "";
  const projOpts = projects.map((p) =>
    `<option value="${p.key}" ${p.key === defProj ? "selected" : ""}>${p.key} — ${p.name}</option>`).join("");

  const isEpic = category === "Epic";
  openModal(`
    <h3>New ${category}${parentRef ? ` under ${parentRef}` : ""}</h3>
    ${field("Project", `<select id="c-project">${projOpts}</select>`)}
    ${field("Issue type", `<select id="c-type"><option>${category}</option></select>`)}
    ${parentRef === null
      ? (isEpic ? "" :
         field("Parent key" + (category === "Sub-task" ? " (required)" : " (optional epic)"),
               `<input type="text" id="c-parent" placeholder="e.g. ISC-123">`))
      : `<input type="hidden" id="c-parent" value="${parentRef}">`}
    ${field("Summary (required)", `<input type="text" id="c-summary">`)}
    ${field("Description", `<textarea id="c-desc"></textarea>`)}
    <div class="row">
      ${field("Priority", `<select id="c-priority"><option value="">—</option>${(META.priorities||[]).map(p=>`<option>${p.name}</option>`).join("")}</select>`)}
      ${field("Target completion date", `<input type="date" id="c-target">`)}
    </div>
    ${isEpic ? `<div class="row">
        ${field("Initial status", `<input type="text" id="c-status" value="In Progress">`)}
        ${field("Epic colour", `<select id="c-color">${EPIC_COLORS.map(c => `<option value="${c}" ${c==="dark_orange"?"selected":""}>${c}</option>`).join("")}</select>`)}
      </div>` : `<input type="hidden" id="c-status" value=""><input type="hidden" id="c-color" value="">`}
    <div id="c-critical"></div>
    ${field("Assignee", assigneeInput("c-assignee", "", defProj))}
    <div class="row">
      ${field("Component", componentSelectHtml("c-component", ""))}
      ${field("Developer", assigneeInput("c-developer", "", defProj))}
    </div>
    ${field("Assigned Group", groupInput("c-group", ""))}
    ${field("Labels", labelsWidget("c-labels", []))}
    ${field("Attachments", `
      <ul class="attach-list" id="c-attach-list"></ul>
      <div class="desc-upload">
        <input type="file" id="c-attach-file" style="display:none" multiple>
        <button type="button" id="c-attach-btn" class="link-btn">📎 Attach file…</button>
        <span class="muted">uploaded when you push</span>
      </div>`)}
    <div class="modal-actions">
      <button onclick="closeModalBtn()">Cancel</button>
      <button class="primary" id="c-submit">Stage ${category}</button>
    </div>`, /* persistent */ true);

  // populate real issue types for the chosen project
  const projSel = document.getElementById("c-project");
  const typeSel = document.getElementById("c-type");
  async function loadTypes() {
    try {
      const { issuetypes } = await api("/api/meta/issuetypes?project=" + encodeURIComponent(projSel.value));
      const wantSub = category === "Sub-task";
      const filtered = issuetypes.filter((t) => t.subtask === wantSub);
      const pool = filtered.length ? filtered : issuetypes;
      const pref = pool.find((t) => t.name.toLowerCase().includes(category.toLowerCase().replace("-", ""))) || pool[0];
      typeSel.innerHTML = pool.map((t) => `<option ${pref && t.name===pref.name?"selected":""}>${t.name}</option>`).join("");
      loadCreateFields(); // refresh available date fields for the chosen type
    } catch (e) { /* keep default */ }
  }
  // which critical date fields are settable on create for this type
  async function loadCreateFields() {
    const box = document.getElementById("c-critical");
    if (!box) return;
    try {
      const { critical } = await api(
        `/api/meta/createfields?project=${encodeURIComponent(projSel.value)}&issuetype=${encodeURIComponent(typeSel.value || category)}`);
      box.innerHTML = critical.length
        ? `<div class="section-label">Dates</div>` + (() => {
            const cells = critical.map((f) =>
              field(f.name, `<input type="date" id="cf-${f.id}" data-cf="${f.id}" data-orig="">`));
            let h = ""; for (let i = 0; i < cells.length; i += 2) h += `<div class="row">${cells[i]||""}${cells[i+1]||""}</div>`;
            return h;
          })()
        : "";
    } catch (e) { box.innerHTML = ""; }
  }
  // Components are project-scoped, so the list must reload on project change
  // (unlike Assignee/Developer, which don't currently re-scope on the fly).
  async function refreshComponents() {
    const sel = document.getElementById("c-component");
    if (!sel) return;
    sel.innerHTML = `<option value="">—</option>`;
    await loadComponentOptions("c-component", projSel.value);
  }
  loadTypes();
  refreshComponents();
  projSel.onchange = () => { loadTypes(); refreshComponents(); };
  wireAssignee("c-assignee", projSel.value);
  wireAssignee("c-developer", projSel.value);
  wireGroup("c-group");

  _pendingCreateFiles = [];
  wirePendingAttach();

  document.getElementById("c-submit").onclick = () => submitCreate(category, parentRef);
}

// ---------- file attachments ----------
let _pendingCreateFiles = [];          // files queued on the create form
const MAX_ATTACH_BYTES = 25 * 1024 * 1024; // 25 MB

function fmtBytes(n) {
  if (!n) return "";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return Math.round(n / 1024) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

function attachmentLi(a) {
  const url = `/api/issue/attachment/${encodeURIComponent(a.id)}?name=${encodeURIComponent(a.filename)}`;
  return `<li class="attach-item" data-id="${a.id}">
    <a href="${url}" target="_blank" rel="noopener">📎 ${escapeHtml(a.filename)}</a>
    ${a.size ? `<span class="muted">${fmtBytes(a.size)}</span>` : ""}
  </li>`;
}

function attachmentsBlock(issue) {
  const list = (issue.attachments || []).map(attachmentLi).join("");
  return `<ul class="attach-list" id="f-attach-list">${list ||
      `<li class="muted attach-empty">No attachments yet.</li>`}</ul>
    <div class="desc-upload">
      <input type="file" id="f-attach-file" style="display:none" multiple>
      <button type="button" id="f-attach-btn" class="link-btn">📎 Attach file…</button>
      <span id="f-attach-status" class="muted"></span>
    </div>`;
}

// Edit view: upload straight to the existing Jira issue.
function wireAttachImmediate(key) {
  const btn = document.getElementById("f-attach-btn");
  const input = document.getElementById("f-attach-file");
  const status = document.getElementById("f-attach-status");
  const list = document.getElementById("f-attach-list");
  if (!btn || !input) return;
  btn.onclick = () => input.click();
  input.onchange = async () => {
    const files = Array.from(input.files || []);
    input.value = "";
    for (const file of files) {
      if (file.size > MAX_ATTACH_BYTES) {
        toast(`“${file.name}” is too large (max 25 MB).`, "error");
        continue;
      }
      if (status) status.textContent = `Uploading “${file.name}”…`;
      try {
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetch(`/api/issue/${encodeURIComponent(key)}/attachments`,
          { method: "POST", body: fd });
        if (!res.ok) {
          let msg = `Couldn't attach “${file.name}”.`;
          try { const j = await res.json(); if (j.detail) msg = j.detail; } catch (_) {}
          throw new Error(msg);
        }
        const data = await res.json();
        const empty = list && list.querySelector(".attach-empty");
        if (empty) empty.remove();
        (data.attachments || []).forEach((a) => {
          if (list) list.insertAdjacentHTML("beforeend", attachmentLi(a));
        });
        toast(`Attached “${file.name}”.`, "success");
      } catch (e) {
        toast(e.message || "Attach failed.", "error");
      } finally {
        if (status) status.textContent = "";
      }
    }
  };
}

// Create view: hold files locally; they're uploaded after the issue is created
// on push (the issue doesn't exist in Jira yet).
function renderPendingAttach() {
  const list = document.getElementById("c-attach-list");
  if (!list) return;
  list.innerHTML = _pendingCreateFiles.length
    ? _pendingCreateFiles.map((f, i) =>
        `<li class="attach-item">📎 ${escapeHtml(f.name)}
           <span class="muted">${fmtBytes(f.size)}</span>
           <button type="button" class="link-btn" onclick="removePendingFile(${i})">remove</button>
         </li>`).join("")
    : "";
}

function removePendingFile(i) {
  _pendingCreateFiles.splice(i, 1);
  renderPendingAttach();
}
window.removePendingFile = removePendingFile;

function wirePendingAttach() {
  const btn = document.getElementById("c-attach-btn");
  const input = document.getElementById("c-attach-file");
  if (!btn || !input) return;
  btn.onclick = () => input.click();
  input.onchange = () => {
    Array.from(input.files || []).forEach((file) => {
      if (file.size > MAX_ATTACH_BYTES) {
        toast(`“${file.name}” is too large (max 25 MB).`, "error");
        return;
      }
      _pendingCreateFiles.push(file);
    });
    input.value = "";
    renderPendingAttach();
  };
}

// Upload the create form's queued files against a now-known ref (tempId).
async function uploadPendingAttachments(ref) {
  for (const file of _pendingCreateFiles) {
    try {
      const fd = new FormData();
      fd.append("ref", ref);
      fd.append("file", file);
      const res = await fetch("/api/stage/attachment", { method: "POST", body: fd });
      if (!res.ok) {
        let msg = `Couldn't stage “${file.name}”.`;
        try { const j = await res.json(); if (j.detail) msg = j.detail; } catch (_) {}
        throw new Error(msg);
      }
    } catch (e) {
      toast(e.message || `Couldn't stage “${file.name}”.`, "error");
    }
  }
  _pendingCreateFiles = [];
}

async function submitCreate(category, parentRef) {
  const summary = document.getElementById("c-summary").value.trim();
  if (!summary) { toast("Summary is required.", "error"); return; }
  const parentEl = document.getElementById("c-parent");
  const parent = parentEl ? parentEl.value.trim() : "";
  if (category === "Sub-task" && !parent) { toast("Sub-tasks need a parent key.", "error"); return; }

  const labels = collectLabels("c-labels");
  const status = (document.getElementById("c-status") || {}).value || null;
  const epicColor = (document.getElementById("c-color") || {}).value || null;
  const custom = {};
  document.querySelectorAll("#c-critical [data-cf]").forEach((el) => {
    if (el.value) custom[el.dataset.cf] = el.value;
  });
  const component = collectComponent("c-component");
  const developer = resolveNamedAssignee("c-developer");
  const group = resolveGroup("c-group");
  const body = {
    project: document.getElementById("c-project").value,
    issuetype: document.getElementById("c-type").value,
    summary,
    description: document.getElementById("c-desc").value || null,
    parentRef: parent || null,
    priority: document.getElementById("c-priority").value || null,
    targetCompletion: (document.getElementById("c-target") || {}).value || null,
    labels: labels.length ? labels : null,
    status: status || null,
    epicColor: category === "Epic" ? epicColor : null,
    assigneeId: resolveAssignee("c-assignee"),
    custom: Object.keys(custom).length ? custom : null,
    componentId: component.id,
    componentName: component.name,
    developerId: developer.id,
    developerName: developer.name,
    assignedGroupId: group.id,
    assignedGroupName: group.name,
  };
  Object.keys(body).forEach((k) => body[k] == null && delete body[k]);

  let op;
  try {
    const res = await api("/api/stage/create", { method: "POST", body: JSON.stringify(body) });
    op = res.op;
    toast(`${category} staged (${res.count} pending).`, "success");
    refreshStageCount();
    await loadTree();
  } catch (e) { toast(e.message, "error"); return; }

  // Queue any attached files against the new item's tempId; they upload to
  // Jira right after the item is created on push.
  if (_pendingCreateFiles.length) await uploadPendingAttachments(op.tempId);

  // ----- guided follow-up prompts (the yes/no flow you described) -----
  await afterCreate(category, op.tempId);
}

async function afterCreate(category, tempId) {
  const childMap = { "Epic": "Story", "Story": "Sub-task" };
  const childType = childMap[category];

  if (childType) {
    const wantsChild = await confirmPrompt(
      `Create a ${childType}?`,
      `Your ${category} is staged. Do you want to create a ${childType} under it now?`,
      `Yes, add a ${childType}`, "No");
    if (wantsChild) {
      openCreateForm(childType, tempId);   // recurses → its own afterCreate continues the chain
      return;
    }
  }
  // End of this branch → ask about closing the session.
  await promptCloseSession();
}

async function promptCloseSession() {
  const close = await confirmPrompt(
    "Close session?",
    "Do you want to close the session and upload ALL staged changes to Jira now?",
    "Yes, upload now", "No, keep editing");
  if (close) await pushChanges();
  else { closeModal(); loadTree(); }
}

// ---------- staging review + push ----------
async function refreshStageCount() {
  try {
    const { count } = await api("/api/staging");
    $("#stage-count").textContent = count;
  } catch (_) {}
}

async function reviewChanges() {
  const { ops } = await api("/api/staging");
  if (!ops.length) {
    openModal(`<h3>No staged changes</h3><p class="muted">Edit or create items first.</p>
      <div class="modal-actions"><button onclick="closeModalBtn()">Close</button></div>`);
    return;
  }
  const items = ops.map((op) => {
    const isCreate = op.kind === "create";
    const isAttach = op.kind === "attachment";
    const title = isCreate ? `${op.data.issuetype}: ${op.data.summary}`
      : isAttach ? `📎 ${op.filename}` : op.key;
    const detail = isCreate
      ? `Project ${op.data.project}${op.data.parentRef ? ", parent " + op.data.parentRef : ""}`
      : isAttach ? `attach to ${op.ref}`
      : Object.keys(op.changes).join(", ");
    return `<div class="stage-item">
      <span class="stage-kind kind-${op.kind}">${op.kind}</span>
      <div class="grow"><div><b>${title}</b></div><div class="muted">${detail}</div>
        ${op.error ? `<div class="stage-error">⚠ ${op.error}</div>` : ""}</div>
      <button class="danger" onclick="removeStaged('${op.id}')">Remove</button>
    </div>`;
  }).join("");

  openModal(`
    <h3>Review staged changes (${ops.length})</h3>
    ${items}
    <div class="modal-actions">
      <button class="danger" onclick="clearStaging()">Discard all</button>
      <button onclick="closeModalBtn()">Keep editing</button>
      <button class="success" onclick="pushChanges()">Push all to Jira</button>
    </div>`);
}

async function removeStaged(id) {
  await api("/api/staging/" + id, { method: "DELETE" });
  toast("Removed from staging.");
  refreshStageCount();
  await loadTree();
  if ($("#modal-overlay").classList.contains("hidden") === false) reviewChanges();
}

async function clearStaging() {
  if (!(await confirmPrompt("Discard all?", "Remove every staged change without pushing?", "Discard all", "Cancel"))) {
    reviewChanges(); return;
  }
  await api("/api/staging", { method: "DELETE" });
  refreshStageCount();
  await loadTree();
  closeModal();
  toast("All staged changes discarded.");
}

async function pushChanges() {
  openModal(`<h3>Pushing to Jira…</h3><p class="muted">Creating and updating issues.</p>`);
  try {
    const report = await api("/api/push", { method: "POST" });
    const created = report.created.map((c) => `${c.tempId} → <b>${c.key}</b> ${c.summary}`).join("<br>") || "—";
    const updated = report.updated.join(", ") || "—";
    const attached = (report.attached || []).map((a) => `${escapeHtml(a.filename)} → <b>${a.key}</b>`).join("<br>");
    const errors = report.errors.map((e) => `<div class="stage-error">${e.op}: ${e.error}</div>`).join("");
    const warnings = (report.warnings || []).map((w) => `<div class="muted">⚠ ${escapeHtml(w.warning || w)}</div>`).join("");
    openModal(`
      <h3>${report.errors.length ? "Pushed with errors" : "✓ Pushed to Jira"}</h3>
      <div class="field"><label>Created</label><div>${created}</div></div>
      <div class="field"><label>Updated</label><div>${updated}</div></div>
      ${attached ? `<div class="field"><label>Attached</label><div>${attached}</div></div>` : ""}
      ${errors ? `<div class="field"><label>Errors (remain staged)</label>${errors}</div>` : ""}
      ${warnings ? `<div class="field"><label>Warnings</label>${warnings}</div>` : ""}
      <div class="modal-actions"><button class="primary" onclick="closeModalBtn()">Done</button></div>`);
    toast(report.errors.length ? "Pushed with some errors." : "All changes pushed.",
          report.errors.length ? "error" : "success");
  } catch (e) {
    openModal(`<h3 class="stage-error">Push failed</h3><p>${e.message}</p>
      <div class="modal-actions"><button onclick="closeModalBtn()">Close</button></div>`);
  }
  refreshStageCount();
  await loadTree(true);
}

window.removeStaged = removeStaged;
window.clearStaging = clearStaging;
window.pushChanges = pushChanges;
window.reviewChanges = reviewChanges;

// ---------- stale on-hold auto-cancel ----------
async function runOnHoldScan(opts = {}) {
  // opts.manual = user clicked the button (force apply even if auto is off)
  // opts.force  = bypass the safety cap after confirmation
  const params = new URLSearchParams();
  if (opts.manual) params.set("apply", "true");
  if (opts.force) params.set("force", "true");
  let r;
  try {
    r = await api("/api/scan/onhold" + (params.toString() ? "?" + params : ""), { method: "POST" });
  } catch (e) {
    if (opts.manual) toast("On-hold scan failed: " + e.message, "error");
    return;
  }

  if (r.capped) {
    const ok = await confirmPrompt(
      "⚠ Safety cap reached",
      `${r.candidates.length} items have been in "${r.onholdStatus}" for over ${r.thresholdMonths} months — ` +
      `more than the safety cap of ${r.cap}. This usually means something unexpected. ` +
      `Cancel all ${r.candidates.length} now?`,
      "Yes, cancel all", "No, leave them");
    if (ok) return runOnHoldScan({ ...opts, force: true });
    return;
  }

  if (!r.applied) {
    // auto-cancel disabled: just report what would qualify
    if (r.candidates.length) {
      toast(`${r.candidates.length} item(s) on hold > ${r.thresholdMonths}mo (auto-cancel is off).`);
    } else if (opts.manual) {
      toast("No items have been on hold past the threshold.", "success");
    }
    return;
  }

  if (r.cancelled.length) {
    toast(`Auto-cancelled ${r.cancelled.length} stale on-hold item(s): ${r.cancelled.map((c) => c.key).join(", ")}`, "success");
    await loadTree(true);
  } else if (opts.manual) {
    toast("No items have been on hold past the threshold.", "success");
  }
  if (r.skipped.length) toast(`${r.skipped.length} skipped (no Cancelled transition).`, "error");
  if (r.errors.length) toast(`${r.errors.length} cancellation error(s) — see console.`, "error");
  if (r.errors.length) console.warn("On-hold cancel errors:", r.errors);
}

// ---------- monthly report ----------
let _reportYear = null, _reportMonth = null;   // currently displayed period

async function openReport(year, month) {
  openModal(`<h3>Monthly Report</h3><p class="muted">Building report…</p>`);
  const params = new URLSearchParams();
  if (year) params.set("year", year);
  if (month) params.set("month", month);
  if (viewedEmail) params.set("email", viewedEmail);
  let data;
  try {
    data = await api("/api/report/data" + (params.toString() ? "?" + params : ""));
  } catch (e) {
    openModal(`<h3 class="stage-error">Report failed</h3><p>${e.message}</p>
      <div class="modal-actions"><button onclick="closeModalBtn()">Close</button></div>`);
    return;
  }
  _reportYear = data.year;
  _reportMonth = data.monthNum;

  let rowsHtml = "";
  let count = 0;
  data.epics.forEach((ep) => {
    const span = ep.stories.reduce((n, st) => n + st.subs.length, 0);
    let epShown = false;
    ep.stories.forEach((st) => {
      st.subs.forEach((s, i) => {
        count++;
        const storyHeader = i === 0
          ? `<b>${st.key}: ${escapeHtml(st.summary)}</b> <span class="muted">(${st.progress})</span>`
            + (st.description ? `<div class="muted rpt-desc">${escapeHtml(st.description)}</div>` : "")
            + `<br>`
          : "";
        const fbNote = s.commentsFallback ? " · latest (none in 4 wks)" : "";
        const updateCell = (s.updates && s.updates.length)
          ? s.updates.map((u) =>
              `<div class="rpt-cmt">${escapeHtml(u.text)}` +
              `<div class="muted rpt-meta">— ${escapeHtml(u.author)}, ${u.date}${fbNote}</div></div>`).join("")
          : `<span class="muted">No comments</span>`;
        const epTitle = ep.key ? `${ep.key}: ${escapeHtml(ep.summary)}` : escapeHtml(ep.summary);
        rowsHtml += `<tr>
          ${!epShown ? `<td rowspan="${span}" class="rpt-epic"><b>${epTitle}</b>${ep.description ? `<div class="muted">${escapeHtml(ep.description)}</div>` : ""}</td>` : ""}
          <td>${storyHeader}↳ ${s.key}: ${escapeHtml(s.summary)}</td>
          <td>${s.start}</td><td>${s.end}</td>
          <td><span class="rag" style="background:${s.ragColor}">${s.rag}</span></td>
          <td>${escapeHtml(s.status || "")}</td>
          <td>${escapeHtml(s.who)}</td>
          <td>${escapeHtml(s.reporter || "\u2014")}</td>
          <td class="rpt-update">${updateCell}</td>
        </tr>`;
        epShown = true;
      });
    });
  });

  const body = count ? `
    <table class="rpt-table">
      <colgroup>
        <col style="width:14%"><col style="width:22%"><col style="width:6%"><col style="width:6%"><col style="width:6%"><col style="width:8%"><col style="width:8%"><col style="width:8%"><col style="width:22%">
      </colgroup>
      <thead><tr><th>Epic</th><th>Story / Sub-task</th><th>Start</th><th>Target end</th><th>Status</th><th>Progress</th><th>Responsible</th><th>Reported by</th><th>Recent comments (4 wks)</th></tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>` : `<p class="muted">No sub-tasks with a Target Completion Date in ${data.month}.</p>`;

  const monthValue = `${data.year}-${String(data.monthNum).padStart(2, "0")}`;
  openModal(`
    <h3>Monthly Report — ${data.month}</h3>
    <div class="rpt-nav">
      <button id="rpt-prev" title="Previous month">◀</button>
      <input type="month" id="rpt-month" value="${monthValue}">
      <button id="rpt-next" title="Next month">▶</button>
      <button id="rpt-this">This month</button>
    </div>
    <p class="muted">For <b>${escapeHtml(data.owner || "me")}</b> · ${count} sub-task(s) with a target end in ${data.month}, across ${data.epics.length} epic(s).</p>
    <div class="rpt-wrap">${body}</div>
    <div class="modal-actions">
      <button onclick="closeModalBtn()">Close</button>
      <button class="success" onclick="downloadReport(${data.year}, ${data.monthNum})">⬇ Download PowerPoint</button>
    </div>`);

  // wire month navigation
  const shift = (delta) => {
    let y = data.year, m = data.monthNum + delta;
    if (m < 1) { m = 12; y -= 1; }
    if (m > 12) { m = 1; y += 1; }
    openReport(y, m);
  };
  $("#rpt-prev").onclick = () => shift(-1);
  $("#rpt-next").onclick = () => shift(1);
  $("#rpt-this").onclick = () => openReport();
  $("#rpt-month").onchange = (e) => {
    const [y, m] = e.target.value.split("-").map(Number);
    if (y && m) openReport(y, m);
  };
}

function downloadReport(year, month) {
  // Content-Disposition on the endpoint triggers the file download.
  const emailParam = viewedEmail ? `&email=${encodeURIComponent(viewedEmail)}` : "";
  window.location.href = `/api/report/pptx?year=${year}&month=${month}${emailParam}`;
  toast("Downloading PowerPoint…", "success");
}
window.downloadReport = downloadReport;

// ---------- wire up ----------
$("#btn-new").onclick = newItemFlow;
$("#btn-report").onclick = () => openReport();
$("#btn-view").onclick = viewUser;
$("#view-email").addEventListener("keydown", (e) => { if (e.key === "Enter") viewUser(); });
$("#btn-refresh").onclick = async () => {
  await loadTree(true);
  // On-hold auto-cancel only applies to your own items, never a colleague's.
  if (META.autoCancelOnHold && viewingSelf) runOnHoldScan();
};
$("#btn-review").onclick = reviewChanges;
$("#btn-onhold").onclick = () => runOnHoldScan({ manual: true });
$("#chk-completed").onchange = () => loadTree(true);

// ---------- tree search wiring ----------
function applySearch(raw) {
  searchTerm = (raw || "").trim().toLowerCase();
  $("#tree-search-clear").classList.toggle("hidden", !searchTerm);
  loadTreeFromCacheRerender();   // filter the already-loaded tree, no Jira hit
}
$("#tree-search").addEventListener("input", (e) => applySearch(e.target.value));
$("#tree-search").addEventListener("keydown", (e) => {
  if (e.key === "Escape") { e.target.value = ""; applySearch(""); }
});
$("#tree-search-clear").onclick = () => {
  const box = $("#tree-search");
  box.value = "";
  applySearch("");
  box.focus();
};

(async function init() {
  await loadMeta();
  await loadTree();
  // "Automatically on every load": run the stale on-hold cancellation now.
  if (META.autoCancelOnHold && viewingSelf) runOnHoldScan();
})();
