"use strict";

// ---------- tiny helpers ----------
const $ = (sel) => document.querySelector(sel);
const collapsed = new Set();          // keys whose children are hidden
let selectedKey = null;
let META = { projects: [], priorities: [], defaultProject: "", rootTypes: [] };

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
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
function openModal(html) {
  $("#modal").innerHTML = html;
  $("#modal-overlay").classList.remove("hidden");
}
function closeModal() { $("#modal-overlay").classList.add("hidden"); }
$("#modal-overlay").addEventListener("click", (e) => {
  if (e.target.id === "modal-overlay") closeModal();
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
  try { META = await api("/api/meta"); } catch (e) { /* config maybe missing */ }
}

async function loadTree(refresh = false) {
  $("#tree").innerHTML = `<p class="muted">Loading…</p>`;
  const showCompleted = $("#chk-completed") && $("#chk-completed").checked;
  const params = new URLSearchParams();
  if (refresh) params.set("refresh", "true");
  if (showCompleted) params.set("show_completed", "true");
  try {
    const data = await api("/api/tree" + (params.toString() ? "?" + params : ""));
    $("#who").textContent = data.me ? `Signed in as ${data.me}` : "";
    renderTree(data.tree);
  } catch (e) {
    $("#tree").innerHTML = `<p class="stage-error">${e.message}</p>`;
  }
  refreshStageCount();
}

function renderTree(nodes) {
  if (!nodes || !nodes.length) {
    $("#tree").innerHTML = `<p class="muted">No epics or tasks assigned to you.</p>`;
    return;
  }
  const root = document.createElement("ul");
  nodes.forEach((n) => root.appendChild(renderNode(n)));
  $("#tree").innerHTML = "";
  $("#tree").appendChild(root);
}

function renderNode(node) {
  const li = document.createElement("li");
  const row = document.createElement("div");
  row.className = "node-row" + (node.key === selectedKey ? " selected" : "");

  const hasKids = node.children && node.children.length;
  const isCollapsed = collapsed.has(node.key);

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

  $("#detail").innerHTML = `
    ${stagedNote}
    <h2>${issue.summary}</h2>
    <p class="muted"><b>${issue.key}</b> · ${issue.type} · reporter ${issue.reporter}
      ${issue.parent ? " · parent " + issue.parent : ""}</p>

    ${field("Summary", `<input type="text" id="f-summary" value="${escapeAttr(issue.summary)}">`)}
    ${field("Description", `<textarea id="f-desc">${escapeHtml(issue.description)}</textarea>`)}
    <div class="row">
      ${field("Status", `<select id="f-status">${statusOpts}</select>`)}
      ${field("Priority", `<select id="f-priority">${priOpts}</select>`)}
    </div>
    <div class="row">
      ${field("Assignee", assigneeInput("f-assignee", issue.assignee && issue.assignee.displayName, issue.project))}
      ${field("Due date", `<input type="date" id="f-duedate" value="${issue.duedate || ""}">`)}
    </div>
    ${field("Labels (comma separated)", `<input type="text" id="f-labels" value="${(issue.labels||[]).join(", ")}">`)}
    ${field("Add comment", `<textarea id="f-comment" placeholder="Leave blank to skip"></textarea>`)}

    <div class="comments"><label class="muted">Existing comments</label>${commentsHtml}</div>

    <div class="detail-actions">
      <button class="primary" onclick="stageIssueUpdate('${issue.key}', '${issue.project}')">Stage changes</button>
      <button onclick="selectItem('${issue.key}')">Reset</button>
    </div>`;
  wireAssignee("f-assignee", issue.project);
}

function escapeHtml(s) { return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function escapeAttr(s) { return escapeHtml(s).replace(/"/g,"&quot;"); }

// Assignee search widget --------------------------------------------------
function assigneeInput(id, current, project) {
  return `<input type="text" id="${id}" list="${id}-list" placeholder="${current || "Search user…"}"
            data-account="" autocomplete="off">
          <datalist id="${id}-list"></datalist>`;
}
function wireAssignee(id, project) {
  const input = document.getElementById(id);
  if (!input) return;
  let timer;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) return;
    timer = setTimeout(async () => {
      try {
        const { users } = await api(`/api/meta/users?project=${encodeURIComponent(project)}&query=${encodeURIComponent(q)}`);
        const dl = document.getElementById(id + "-list");
        dl.innerHTML = users.map((u) => `<option data-account="${u.accountId}" value="${u.displayName}">`).join("");
        input._users = users;
      } catch (_) {}
    }, 300);
  });
}
function resolveAssignee(id) {
  const input = document.getElementById(id);
  if (!input || !input.value.trim()) return null;
  const match = (input._users || []).find((u) => u.displayName === input.value.trim());
  return match ? match.accountId : null;
}

// Collect edit form into a changes object
function collectChanges() {
  const labelsRaw = document.getElementById("f-labels").value.trim();
  return {
    summary: document.getElementById("f-summary").value.trim() || null,
    description: document.getElementById("f-desc").value,
    status: document.getElementById("f-status").value || null,
    priority: document.getElementById("f-priority").value || null,
    duedate: document.getElementById("f-duedate").value || null,
    labels: labelsRaw ? labelsRaw.split(",").map((s) => s.trim()).filter(Boolean) : null,
    comment: document.getElementById("f-comment").value.trim() || null,
    assigneeId: resolveAssignee("f-assignee"),
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

window.stageIssueUpdate = stageIssueUpdate;
window.removeStaged = removeStaged;
window.selectItem = selectItem;

// ---------- create wizard ----------
function newItemFlow() {
  openModal(`
    <h3>What do you want to create?</h3>
    <div class="choice-grid">
      <div class="choice" data-cat="Epic"><div class="big">🏔️</div><div>Epic</div></div>
      <div class="choice" data-cat="Task"><div class="big">✅</div><div>Task</div></div>
      <div class="choice" data-cat="Sub-task"><div class="big">↳</div><div>Sub-task</div></div>
    </div>
    <div class="modal-actions"><button onclick="closeModalBtn()">Cancel</button></div>`);
  document.querySelectorAll(".choice").forEach((c) => {
    c.onclick = () => openCreateForm(c.dataset.cat, null);
  });
}
window.closeModalBtn = closeModal;

async function openCreateForm(category, parentRef) {
  const projects = META.projects || [];
  const defProj = META.defaultProject || (projects[0] && projects[0].key) || "";
  const projOpts = projects.map((p) =>
    `<option value="${p.key}" ${p.key === defProj ? "selected" : ""}>${p.key} — ${p.name}</option>`).join("");

  openModal(`
    <h3>New ${category}${parentRef ? ` under ${parentRef}` : ""}</h3>
    ${field("Project", `<select id="c-project">${projOpts}</select>`)}
    ${field("Issue type", `<select id="c-type"><option>${category}</option></select>`)}
    ${parentRef === null
      ? (category === "Epic" ? "" :
         field("Parent key" + (category === "Sub-task" ? " (required)" : " (optional epic)"),
               `<input type="text" id="c-parent" placeholder="e.g. PROJ-123">`))
      : `<input type="hidden" id="c-parent" value="${parentRef}">`}
    ${field("Summary (required)", `<input type="text" id="c-summary">`)}
    ${field("Description", `<textarea id="c-desc"></textarea>`)}
    <div class="row">
      ${field("Priority", `<select id="c-priority"><option value="">—</option>${(META.priorities||[]).map(p=>`<option>${p.name}</option>`).join("")}</select>`)}
      ${field("Due date", `<input type="date" id="c-duedate">`)}
    </div>
    ${field("Assignee", assigneeInput("c-assignee", "", defProj))}
    ${field("Labels (comma separated)", `<input type="text" id="c-labels">`)}
    <div class="modal-actions">
      <button onclick="closeModalBtn()">Cancel</button>
      <button class="primary" id="c-submit">Stage ${category}</button>
    </div>`);

  // populate real issue types for the chosen project
  const projSel = document.getElementById("c-project");
  const typeSel = document.getElementById("c-type");
  async function loadTypes() {
    try {
      const { issuetypes } = await api("/api/meta/issuetypes?project=" + encodeURIComponent(projSel.value));
      const wantSub = category === "Sub-task";
      const filtered = issuetypes.filter((t) => t.subtask === wantSub);
      const pool = filtered.length ? filtered : issuetypes;
      // try to preselect by name match
      const pref = pool.find((t) => t.name.toLowerCase().includes(category.toLowerCase().replace("-", ""))) || pool[0];
      typeSel.innerHTML = pool.map((t) => `<option ${pref && t.name===pref.name?"selected":""}>${t.name}</option>`).join("");
    } catch (e) { /* keep default */ }
  }
  loadTypes();
  projSel.onchange = loadTypes;
  wireAssignee("c-assignee", projSel.value);

  document.getElementById("c-submit").onclick = () => submitCreate(category, parentRef);
}

async function submitCreate(category, parentRef) {
  const summary = document.getElementById("c-summary").value.trim();
  if (!summary) { toast("Summary is required.", "error"); return; }
  const parentEl = document.getElementById("c-parent");
  const parent = parentEl ? parentEl.value.trim() : "";
  if (category === "Sub-task" && !parent) { toast("Sub-tasks need a parent key.", "error"); return; }

  const labelsRaw = document.getElementById("c-labels").value.trim();
  const body = {
    project: document.getElementById("c-project").value,
    issuetype: document.getElementById("c-type").value,
    summary,
    description: document.getElementById("c-desc").value || null,
    parentRef: parent || null,
    priority: document.getElementById("c-priority").value || null,
    duedate: document.getElementById("c-duedate").value || null,
    labels: labelsRaw ? labelsRaw.split(",").map(s=>s.trim()).filter(Boolean) : null,
    assigneeId: resolveAssignee("c-assignee"),
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

  // ----- guided follow-up prompts (the yes/no flow you described) -----
  await afterCreate(category, op.tempId);
}

async function afterCreate(category, tempId) {
  const childMap = { "Epic": "Task", "Task": "Sub-task", "Story": "Sub-task" };
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
    const title = isCreate ? `${op.data.issuetype}: ${op.data.summary}` : op.key;
    const detail = isCreate
      ? `Project ${op.data.project}${op.data.parentRef ? ", parent " + op.data.parentRef : ""}`
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
    const errors = report.errors.map((e) => `<div class="stage-error">${e.op}: ${e.error}</div>`).join("");
    openModal(`
      <h3>${report.errors.length ? "Pushed with errors" : "✓ Pushed to Jira"}</h3>
      <div class="field"><label>Created</label><div>${created}</div></div>
      <div class="field"><label>Updated</label><div>${updated}</div></div>
      ${errors ? `<div class="field"><label>Errors (remain staged)</label>${errors}</div>` : ""}
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

// ---------- wire up ----------
$("#btn-new").onclick = newItemFlow;
$("#btn-refresh").onclick = () => loadTree(true);
$("#btn-review").onclick = reviewChanges;
$("#chk-completed").onchange = () => loadTree(true);

(async function init() {
  await loadMeta();
  await loadTree();
})();
