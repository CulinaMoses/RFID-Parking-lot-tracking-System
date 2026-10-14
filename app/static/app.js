/*

"use strict";
const $ = (s, r = document) => r.querySelector(s);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const when = s => s ? new Date(s + "Z").toLocaleString() : "";          // server times are UTC
const tag = v => `<span class="tag t-${esc(v)}">${esc(v)}</span>`;
let user = null, tab = null, gateState = null;

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    method: opts.method || "GET", credentials: "same-origin",
    headers: opts.body ? {"Content-Type": "application/json"} : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (res.status === 401 && path !== "/auth/login") { showLogin(); throw new Error("Please sign in"); }
  if (!res.ok) throw new Error(data?.error || res.statusText);
  return data;
}
const fields = form => Object.fromEntries(new FormData(form).entries());
const isoLocalToUtc = v => v ? new Date(v).toISOString().slice(0, 19) : "";
const randomUid = () => Array.from(crypto.getRandomValues(new Uint8Array(6)), b => b.toString(16).padStart(2, "0")).join("").toUpperCase();
function say(el, msg, good) { el.textContent = msg; el.className = good ? "ok" : "error"; }

const TABS = {
  gate:      {label: "Gate console", roles: ["ADMIN","SECURITY"], render: gateView},
  dashboard: {label: "Dashboard",    roles: ["ADMIN","SECURITY","ICT"], render: dashView},
  vehicles:  {label: "Vehicles",     roles: ["ADMIN","SECURITY"], render: vehiclesView},
  visitors:  {label: "Visitors",     roles: ["ADMIN","SECURITY"], render: visitorsView},
  alerts:    {label: "Alerts",       roles: ["ADMIN","SECURITY","ICT"], render: alertsView},
  events:    {label: "Events & reports", roles: ["ADMIN","SECURITY"], render: eventsView},
  admin:     {label: "Users & audit", roles: ["ADMIN","ICT"], render: adminView},
};

function showLogin() { user = null; $("#bar").hidden = true; $("#view").hidden = true; $("#login").hidden = false; }
function showApp() {
  $("#login").hidden = true; $("#bar").hidden = false; $("#view").hidden = false;
  $("#who").textContent = `${user.username} (${user.role.toLowerCase()})`;
  const allowed = Object.entries(TABS).filter(([, t]) => t.roles.includes(user.role));
  $("#tabs").innerHTML = allowed.map(([k, t]) => `<button data-tab="${k}">${esc(t.label)}</button>`).join("");
  go(allowed[0][0]);
}
async function go(name) {
  tab = name;
  document.querySelectorAll("#tabs button").forEach(b => b.dataset.tab === name ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"));
  const v = $("#view"); v.innerHTML = '<p class="muted">Loading…</p>';
  try { await TABS[name].render(v); } catch (e) { v.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}
*/
/* ---------------------------------------------------------------- gate */
/*
async function gateView(v) {
  const gates = await api("/gates");
  gateState = await api("/sim/state?gate_id=" + gates[0].gate_id);
  v.innerHTML = `
  <div class="grid cols-2">
    <div class="card">
      <h2>Gate console</h2>
      <div class="barrier" id="barrier"><div class="post"></div><div class="arm"></div></div>
      <div class="verdict" id="verdict"><strong>Waiting for a vehicle</strong><span class="muted">Simulated reader: enter a tag UID below.</span></div>
      <form id="read-form" style="margin-top:1rem">
        <div class="row">
          <label>Gate <select name="gate_id">${gates.map(g => `<option value="${g.gate_id}">${esc(g.name)} (${esc(g.lot)})</option>`).join("")}</select></label>
          <label>Direction <select name="direction"><option>ENTRY</option><option>EXIT</option></select></label>
        </div>
        <label>Tag UID <input name="uid" placeholder="Leave empty to simulate 'no tag read'" autocomplete="off"></label>
        <button type="submit">Present tag</button>
        <p class="error" id="read-error" role="alert"></p>
      </form>
    </div>
    <div class="grid">
      <div class="card" id="net"></div>
      <div class="card">
        <h3>Manual override</h3>
        <p class="muted">For damaged or missing tags. Needs a reason; it is logged, audited and raises an alert.</p>
        <form id="override-form"><div class="row">
          <label>Direction <select name="direction"><option>ENTRY</option><option>EXIT</option></select></label>
          <label>Reason <input name="note" required maxlength="200"></label>
          <button class="danger" type="submit">Open gate</button></div>
          <p id="override-msg" role="status"></p></form>
      </div>
    </div>
  </div>
  <div class="card" style="margin-top:1rem"><h3>Latest events</h3><div class="table-wrap" id="latest"></div></div>`;
  drawNet(); refreshLatest();

  $("#read-form").onsubmit = async e => {
    e.preventDefault(); const f = fields(e.target); const err = $("#read-error"); err.textContent = "";
    try {
      const r = await api("/sim/read", {method: "POST", body: {gate_id: +f.gate_id, direction: f.direction, uid: f.uid.trim() || null}});
      gateState = r.gate; showVerdict(r); drawNet(); refreshLatest();
    } catch (x) { say(err, x.message); }
  };
  $("#override-form").onsubmit = async e => {
    e.preventDefault(); const f = fields(e.target); const msg = $("#override-msg");
    try {
      await api("/gate/override", {method: "POST", body: {gate_id: +$("#read-form [name=gate_id]").value, direction: f.direction, note: f.note}});
      say(msg, "Override recorded.", true); e.target.reset(); refreshLatest();
    } catch (x) { say(msg, x.message); }
  };
}
function showVerdict(r) {
  const cls = r.action === "ADMIT" ? "go" : r.action === "NO_READ" ? "amber" : r.action === "IGNORED" ? "" : "stop";
  const title = {ADMIT: "Admitted", DENY: "Denied", NO_READ: "No tag read", IGNORED: "Ignored"}[r.action];
  $("#verdict").className = "verdict " + cls;
  $("#verdict").innerHTML = `<strong>${esc(title)}</strong>${esc(r.reason)}` +
    (r.alerts?.length ? `<br><span class="error">Alert: ${r.alerts.map(esc).join(", ")}</span>` : "") +
    `<br><span class="muted">${esc(r.mode)} · decided by ${r.path === "SERVER" ? "server" : "gate controller"}${r.buzzer ? " · buzzer" : ""}</span>`;
  const b = $("#barrier"); b.classList.toggle("open", !!r.barrier_open);
  if (r.barrier_open) setTimeout(() => b.classList.remove("open"), 3500);
}
function drawNet() {
  const g = gateState, on = g.mode === "ONLINE";
  $("#net").innerHTML = `<h3>Server link <span class="pill ${on ? "" : "off"}">${esc(g.mode)}</span></h3>
    <p class="muted">${g.whitelist_size} tags on the gate whitelist · ${g.pending} event(s) waiting to sync.</p>
    <div class="row"><button id="toggle-net" class="ghost">${on ? "Simulate server outage" : "Restore connection"}</button>
    <button id="sync-btn" ${on ? "" : "disabled"}>Sync now</button></div><p id="net-msg" role="status"></p>`;
  $("#toggle-net").onclick = async () => { gateState = await api("/sim/network", {method: "POST", body: {gate_id: 1, online: !on}}); drawNet(); };
  $("#sync-btn").onclick = async () => {
    const r = await api("/sim/sync", {method: "POST", body: {gate_id: 1}}); gateState = r.gate; drawNet();
    say($("#net-msg"), `Synced ${r.synced} event(s).`, true); refreshLatest();
  };
}
async function refreshLatest() {
  const rows = await api("/events?limit=8");
  $("#latest").innerHTML = eventsTable(rows);
}
function eventsTable(rows) {
  if (!rows.length) return '<p class="muted">No events yet.</p>';
  return `<table><thead><tr><th>Time</th><th>Gate</th><th>Dir</th><th>Plate</th><th>Decision</th><th>Reason</th><th>Source</th></tr></thead><tbody>` +
    rows.map(r => `<tr><td>${esc(when(r.occurred_at))}</td><td>${esc(r.gate)}</td><td>${esc(r.direction)}</td><td>${esc(r.plate || "")}</td><td>${tag(r.decision)}</td><td>${esc(r.reason)}</td><td>${esc(r.source)}</td></tr>`).join("") + "</tbody></table>";
}
*/
/* ----------------------------------------------------------- dashboard */
/*
async function dashView(v) {
  const d = await api("/dashboard");
  const stat = (n, l) => `<div class="card stat"><b>${esc(n)}</b><span>${esc(l)}</span></div>`;
  v.innerHTML = `<h2>Dashboard</h2><div class="grid cols-4">
    ${stat(d.vehicles_inside, "vehicles inside")}${stat(d.registered_vehicles, "registered vehicles")}
    ${stat(d.admitted_today, "admitted today (UTC)")}${stat(d.denied_today, "denied today (UTC)")}${stat(d.open_alerts, "open alerts")}</div>
    <div class="card" style="margin-top:1rem"><h3>Parking lots</h3><table><thead><tr><th>Lot</th><th>Inside</th><th>Capacity</th><th>Free</th></tr></thead><tbody>` +
    d.lots.map(l => `<tr><td>${esc(l.name)}</td><td>${l.current_count}</td><td>${l.capacity}</td><td>${Math.max(0, l.capacity - l.current_count)}</td></tr>`).join("") + "</tbody></table></div>";
}
*/
/* ------------------------------------------------------------ vehicles */
/*async function vehiclesView(v) {
  const rows = await api("/vehicles"), admin = user.role === "ADMIN";
  v.innerHTML = `<h2>Vehicles and tags</h2>` + (admin ? `
    <div class="card"><h3>Register vehicle</h3><form id="veh-form">
      <div class="row"><label>Owner name <input name="full_name" required></label>
        <label>Category <select name="category"><option>STAFF</option><option>STUDENT</option><option>CONTRACTOR</option><option>OTHER</option></select></label>
        <label>Department <input name="department"></label></div>
      <div class="row"><label>Plate <input name="plate" required></label><label>Make / model <input name="make_model"></label>
        <label>Colour <input name="colour"></label>
        <label>Tag UID (optional) <input name="uid" placeholder="e.g. E2801160…"></label>
        <button type="submit">Register</button></div><p id="veh-msg" role="status"></p></form></div>` : "") + `
    <div class="card" style="margin-top:1rem"><div class="table-wrap"><table><thead><tr><th>Plate</th><th>Owner</th><th>Category</th><th>Status</th><th>Tags</th>${admin ? "<th>Actions</th>" : ""}</tr></thead><tbody>` +
    rows.map(r => `<tr><td>${esc(r.plate)}</td><td>${esc(r.full_name)}</td><td>${esc(r.category)}</td><td>${tag(r.status)}</td>
      <td>${r.tags.map(t => `#${t.tag_id} ${tag(t.state)}`).join("<br>") || '<span class="muted">none</span>'}</td>
      ${admin ? `<td>
        <select data-veh="${r.vehicle_id}" aria-label="Vehicle status"><option ${r.status==="ACTIVE"?"selected":""}>ACTIVE</option><option ${r.status==="SUSPENDED"?"selected":""}>SUSPENDED</option><option ${r.status==="BLACKLISTED"?"selected":""}>BLACKLISTED</option></select>
        ${r.tags.map(t => `<select data-tag="${t.tag_id}" aria-label="Tag ${t.tag_id} state"><option ${t.state==="ACTIVE"?"selected":""}>ACTIVE</option><option ${t.state==="SUSPENDED"?"selected":""}>SUSPENDED</option><option ${t.state==="REVOKED"?"selected":""}>REVOKED</option></select>`).join("")}
        <button class="small ghost" data-addtag="${r.vehicle_id}">Add tag</button></td>` : ""}</tr>`).join("") + "</tbody></table></div></div>";
  if (!admin) return;
  $("#veh-form").onsubmit = async e => {
    e.preventDefault(); const f = fields(e.target), msg = $("#veh-msg");
    try {
      const r = await api("/vehicles", {method: "POST", body: {plate: f.plate, make_model: f.make_model, colour: f.colour,
        owner: {full_name: f.full_name, category: f.category, department: f.department}}});
      if (f.uid.trim()) await api(`/vehicles/${r.vehicle_id}/tags`, {method: "POST", body: {uid: f.uid.trim()}});
      go("vehicles");
    } catch (x) { say(msg, x.message); }
  };
  v.onchange = async e => {
    const t = e.target;
    try {
      if (t.dataset.veh) await api("/vehicles/" + t.dataset.veh, {method: "PATCH", body: {status: t.value}});
      if (t.dataset.tag) await api("/tags/" + t.dataset.tag, {method: "PATCH", body: {state: t.value}});
    } catch (x) { alert(x.message); go("vehicles"); }
  };
  v.onclick = async e => {
    const id = e.target.dataset?.addtag; if (!id) return;
    const uid = prompt("Tag UID (hex). Leave blank to generate a random one:", "");
    if (uid === null) return;
    const use = uid.trim() || randomUid();
    try { await api(`/vehicles/${id}/tags`, {method: "POST", body: {uid: use}}); alert("Tag issued. UID: " + use + "\nNote it down: only a hash is stored."); go("vehicles"); }
    catch (x) { alert(x.message); }
  };
}
*/
/* ------------------------------------------------------------ visitors */
/*
async function visitorsView(v) {
  const rows = await api("/visitor-passes");
  const pad = n => String(n).padStart(2, "0"), d = new Date(), local = x => `${x.getFullYear()}-${pad(x.getMonth()+1)}-${pad(x.getDate())}T${pad(x.getHours())}:${pad(x.getMinutes())}`;
  const end = new Date(d.getTime() + 4 * 3600e3);
  v.innerHTML = `<h2>Visitor passes</h2><div class="card"><form id="pass-form">
    <div class="row"><label>Visitor <input name="visitor_name" required></label><label>Plate <input name="plate" required></label><label>Host <input name="host"></label></div>
    <div class="row"><label>Loan tag UID <input name="uid" required value="${randomUid()}"></label>
      <label>Valid from <input type="datetime-local" name="valid_from" value="${local(d)}" required></label>
      <label>Valid until <input type="datetime-local" name="valid_until" value="${local(end)}" required></label>
      <button type="submit">Issue pass</button></div><p id="pass-msg" role="status"></p></form></div>
    <div class="card" style="margin-top:1rem"><div class="table-wrap"><table><thead><tr><th>Visitor</th><th>Plate</th><th>Host</th><th>Valid from</th><th>Valid until</th><th>State</th><th></th></tr></thead><tbody>` +
    rows.map(r => `<tr><td>${esc(r.visitor_name)}</td><td>${esc(r.plate)}</td><td>${esc(r.host)}</td><td>${esc(when(r.valid_from))}</td><td>${esc(when(r.valid_until))}</td><td>${tag(r.state)}</td>
      <td>${r.state === "ACTIVE" ? `<button class="small ghost" data-cancel="${r.pass_id}">Cancel</button>` : ""}</td></tr>`).join("") + "</tbody></table></div></div>";
  $("#pass-form").onsubmit = async e => {
    e.preventDefault(); const f = fields(e.target), msg = $("#pass-msg");
    try {
      await api("/visitor-passes", {method: "POST", body: {...f, valid_from: isoLocalToUtc(f.valid_from), valid_until: isoLocalToUtc(f.valid_until)}});
      go("visitors");
    } catch (x) { say(msg, x.message); }
  };
  v.onclick = async e => { const id = e.target.dataset?.cancel; if (id) { await api(`/visitor-passes/${id}/cancel`, {method: "POST"}); go("visitors"); } };
}
*/
/* -------------------------------------------------------------- alerts */
/*
async function alertsView(v) {
  const rows = await api("/alerts"), canAck = ["ADMIN", "SECURITY"].includes(user.role);
  v.innerHTML = `<h2>Alerts</h2><div class="card"><div class="table-wrap">` + (rows.length ? `<table><thead><tr><th>Time</th><th>Type</th><th>Message</th><th>Status</th><th></th></tr></thead><tbody>` +
    rows.map(r => `<tr><td>${esc(when(r.created_at))}</td><td>${esc(r.type)}</td><td>${esc(r.message)}</td><td>${tag(r.status)}${r.acknowledged_by ? " by " + esc(r.acknowledged_by) : ""}</td>
      <td>${canAck && r.status === "OPEN" ? `<button class="small" data-ack="${r.alert_id}">Acknowledge</button>` : ""}</td></tr>`).join("") + "</tbody></table>" : '<p class="muted">No alerts.</p>') + "</div></div>";
  v.onclick = async e => { const id = e.target.dataset?.ack; if (id) { await api(`/alerts/${id}/ack`, {method: "POST"}); go("alerts"); } };
}
*/
/* ------------------------------------------------------ events/reports */
/*
async function eventsView(v) {
  v.innerHTML = `<h2>Events and reports</h2><div class="card"><form id="ev-form"><div class="row">
    <label>From (UTC date) <input type="date" name="start"></label><label>To (UTC date, exclusive) <input type="date" name="end"></label>
    <label>Decision <select name="decision"><option value="">All</option><option>ADMITTED</option><option>DENIED</option></select></label>
    <button type="submit">Filter</button><button type="button" id="csv" class="ghost">Download CSV</button></div></form></div>
    <div class="card" style="margin-top:1rem"><div class="table-wrap" id="ev-table"></div></div>`;
  const q = () => {
    const p = new URLSearchParams(Object.entries(fields($("#ev-form"))).filter(([, x]) => x));
    if (p.get("start")) p.set("start", p.get("start") + "T00:00:00");   // plain dates -> API timestamps
    if (p.get("end")) p.set("end", p.get("end") + "T00:00:00");
    return p.toString();
  };
  const load = async () => { $("#ev-table").innerHTML = eventsTable(await api("/events?limit=200&" + q())); };
  $("#ev-form").onsubmit = e => { e.preventDefault(); load(); };
  $("#csv").onclick = () => { const f = fields($("#ev-form")); const p = new URLSearchParams(); if (f.start) p.set("start", f.start + "T00:00:00"); if (f.end) p.set("end", f.end + "T00:00:00"); location.href = "/api/reports/events.csv?" + p; };
  load();
}
  */
/* --------------------------------------------------------- users/audit */
/*
async function adminView(v) {
  const [users, audit] = await Promise.all([api("/users"), api("/audit")]);
  v.innerHTML = `<h2>Users and audit log</h2><div class="grid cols-2"><div class="card"><h3>Create account</h3><form id="user-form">
    <label>Username <input name="username" required></label><label>Password (min 8) <input name="password" type="password" autocomplete="new-password" required></label>
    <label>Role <select name="role"><option>SECURITY</option><option>ICT</option><option>ADMIN</option></select></label>
    <button type="submit">Create</button><p id="user-msg" role="status"></p></form></div>
    <div class="card"><h3>Accounts</h3><table><thead><tr><th>User</th><th>Role</th><th>Active</th></tr></thead><tbody>` +
    users.map(u => `<tr><td>${esc(u.username)}</td><td>${esc(u.role)}</td><td><input type="checkbox" data-user="${u.user_id}" ${u.active ? "checked" : ""} aria-label="Active: ${esc(u.username)}" style="width:auto"></td></tr>`).join("") + `</tbody></table></div></div>
    <div class="card" style="margin-top:1rem"><h3>Audit log</h3><div class="table-wrap"><table><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Detail</th></tr></thead><tbody>` +
    audit.map(a => `<tr><td>${esc(when(a.at))}</td><td>${esc(a.username)}</td><td>${esc(a.action)}</td><td>${esc(a.detail)}</td></tr>`).join("") + "</tbody></table></div></div>";
  $("#user-form").onsubmit = async e => {
    e.preventDefault(); const msg = $("#user-msg");
    try { await api("/users", {method: "POST", body: fields(e.target)}); go("admin"); } catch (x) { say(msg, x.message); }
  };
  v.onchange = async e => { const id = e.target.dataset?.user; if (!id) return;
    try { await api("/users/" + id, {method: "PATCH", body: {active: e.target.checked}}); } catch (x) { alert(x.message); go("admin"); } };
}
*/

/* ---------------------------------------------------------------- boot */
/*
$("#tabs").onclick = e => { const k = e.target.dataset?.tab; if (k) go(k); };
$("#logout").onclick = async () => { await api("/auth/logout", {method: "POST"}); showLogin(); };
$("#login-form").onsubmit = async e => {
  e.preventDefault(); const err = $("#login-error"); err.textContent = "";
  try { user = await api("/auth/login", {method: "POST", body: fields(e.target)}); e.target.reset(); showApp(); }
  catch (x) { err.textContent = x.message; }
};
(async () => { try { user = await api("/auth/me"); showApp(); } catch { showLogin(); } })();
*/

"use strict";

/* =========================================
   DOM HELPERS AND SHARED STATE
   ========================================= */

const $ = (s, r = document) => r.querySelector(s);

const esc = v =>
  String(v ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[c]);

// Server timestamps are UTC.
const when = s =>
  s ? new Date(s + "Z").toLocaleString() : "";

const tag = v =>
  `<span class="tag t-${esc(v)}">${esc(v)}</span>`;

let user = null;
let tab = null;
let gateState = null;


/* =========================================
   API HELPER
   ========================================= */

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    method: opts.method || "GET",
    credentials: "same-origin",
    headers: opts.body
      ? { "Content-Type": "application/json" }
      : {},
    body: opts.body
      ? JSON.stringify(opts.body)
      : undefined
  });

  const data = res.headers
    .get("content-type")
    ?.includes("json")
      ? await res.json()
      : null;

  if (res.status === 401 && path !== "/auth/login") {
    showLogin();
    throw new Error("Please sign in");
  }

  if (!res.ok) {
    throw new Error(data?.error || res.statusText);
  }

  return data;
}


const fields = form =>
  Object.fromEntries(new FormData(form).entries());

const isoLocalToUtc = v =>
  v ? new Date(v).toISOString().slice(0, 19) : "";

const randomUid = () =>
  Array.from(
    crypto.getRandomValues(new Uint8Array(6)),
    b => b.toString(16).padStart(2, "0")
  ).join("").toUpperCase();

function say(el, msg, good = false) {
  el.textContent = msg;
  el.className = good ? "ok" : "error";
}


/* =========================================
   RESPONSIVE NAVIGATION
   ========================================= */

const sidebar = $("#bar");
const navToggle = $("#nav-toggle");
const tabsElement = $("#tabs");

function closeMobileNav() {
  if (!sidebar || !navToggle) return;

  sidebar.classList.remove("nav-open");

  navToggle.setAttribute("aria-expanded", "false");
  navToggle.setAttribute("aria-label", "Open navigation");

  const icon = navToggle.querySelector(".menu-icon");

  if (icon) {
    icon.textContent = "☰";
  }
}

function toggleMobileNav() {
  if (!sidebar || !navToggle) return;

  const isOpen = sidebar.classList.toggle("nav-open");

  navToggle.setAttribute("aria-expanded", String(isOpen));
  navToggle.setAttribute(
    "aria-label",
    isOpen ? "Close navigation" : "Open navigation"
  );

  const icon = navToggle.querySelector(".menu-icon");

  if (icon) {
    icon.textContent = isOpen ? "✕" : "☰";
  }
}

// Open and close the mobile dropdown.
navToggle?.addEventListener("click", toggleMobileNav);

// Escape closes the dropdown.
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    closeMobileNav();
  }
});

// Reset the dropdown when switching back to desktop.
const mobileQuery = window.matchMedia("(max-width: 760px)");

mobileQuery.addEventListener("change", () => {
  closeMobileNav();
});


/* =========================================
   ROLE-BASED NAVIGATION
   ========================================= */

const TABS = {
  gate: {
    label: "Gate console",
    roles: ["ADMIN", "SECURITY"],
    render: gateView
  },

  dashboard: {
    label: "Dashboard",
    roles: ["ADMIN", "SECURITY", "ICT"],
    render: dashView
  },

  vehicles: {
    label: "Vehicles",
    roles: ["ADMIN", "SECURITY"],
    render: vehiclesView
  },

  visitors: {
    label: "Visitors",
    roles: ["ADMIN", "SECURITY"],
    render: visitorsView
  },

  alerts: {
    label: "Alerts",
    roles: ["ADMIN", "SECURITY", "ICT"],
    render: alertsView
  },

  events: {
    label: "Events & reports",
    roles: ["ADMIN", "SECURITY"],
    render: eventsView
  },

  admin: {
    label: "Users & audit",
    roles: ["ADMIN", "ICT"],
    render: adminView
  }
};


/* =========================================
   LOGIN AND APPLICATION DISPLAY
   ========================================= */

function showLogin() {
  user = null;
  tab = null;

  closeMobileNav();

  $("#bar").hidden = true;
  $("#view").hidden = true;
  $("#login").hidden = false;
}

function showApp() {
  $("#login").hidden = true;
  $("#bar").hidden = false;
  $("#view").hidden = false;

  closeMobileNav();

  $("#who").textContent =
    `${user.username} (${user.role.toLowerCase()})`;

  const allowed = Object.entries(TABS)
    .filter(([, t]) => t.roles.includes(user.role));

  $("#tabs").innerHTML = allowed
    .map(([k, t]) =>
      `<button type="button" data-tab="${k}">${esc(t.label)}</button>`
    )
    .join("");

  // Open the first tab available to this user.
  if (allowed.length) {
    go(allowed[0][0]);
  } else {
    $("#view").innerHTML =
      '<p class="error">No sections are available for your account.</p>';
  }
}

async function go(name) {
  if (!TABS[name]) return;

  if (!user || !TABS[name].roles.includes(user.role)) {
    return;
  }

  tab = name;

  document.querySelectorAll("#tabs button").forEach(button => {
    if (button.dataset.tab === name) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });

  // Selecting a section closes the mobile dropdown.
  closeMobileNav();

  const view = $("#view");

  view.innerHTML = '<p class="muted">Loading…</p>';

  try {
    await TABS[name].render(view);
  } catch (e) {
    view.innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }

  // Move keyboard focus to the new section without scrolling
  // unnecessarily. The main element has tabindex="-1".
  view.focus({ preventScroll: true });
}


/* =========================================
   GATE CONSOLE
   ========================================= */

async function gateView(v) {
  const gates = await api("/gates");

  if (!gates.length) {
    v.innerHTML = '<p class="error">No gates are configured.</p>';
    return;
  }

  gateState = await api(
    "/sim/state?gate_id=" + gates[0].gate_id
  );

  v.innerHTML = `
    <div class="grid cols-2">

      <div class="card">
        <h2>Gate console</h2>

        <div class="barrier" id="barrier">
          <div class="post"></div>
          <div class="arm"></div>
        </div>

        <div class="verdict" id="verdict">
          <strong>Waiting for a vehicle</strong>
          <span class="muted">
            Simulated reader: enter a tag UID below.
          </span>
        </div>

        <form id="read-form" style="margin-top:1rem">

          <div class="row">
            <label>
              Gate
              <select name="gate_id">
                ${gates.map(g => `
                  <option value="${g.gate_id}">
                    ${esc(g.name)} (${esc(g.lot)})
                  </option>
                `).join("")}
              </select>
            </label>

            <label>
              Direction
              <select name="direction">
                <option>ENTRY</option>
                <option>EXIT</option>
              </select>
            </label>
          </div>

          <label>
            Tag UID
            <input
              name="uid"
              placeholder="Leave empty to simulate 'no tag read'"
              autocomplete="off"
            >
          </label>

          <button type="submit">Present tag</button>

          <p class="error" id="read-error" role="alert"></p>
        </form>
      </div>

      <div class="grid">

        <div class="card" id="net"></div>

        <div class="card">
          <h3>Manual override</h3>

          <p class="muted">
            For damaged or missing tags. Needs a reason;
            it is logged, audited and raises an alert.
          </p>

          <form id="override-form">
            <div class="row">

              <label>
                Direction
                <select name="direction">
                  <option>ENTRY</option>
                  <option>EXIT</option>
                </select>
              </label>

              <label>
                Reason
                <input name="note" required maxlength="200">
              </label>

              <button class="danger" type="submit">Open gate</button>
            </div>

            <p id="override-msg" role="status"></p>
          </form>
        </div>

      </div>
    </div>

    <div class="card" style="margin-top:1rem">
      <h3>Latest events</h3>
      <div class="table-wrap" id="latest"></div>
    </div>
  `;

  drawNet();
  refreshLatest();

  $("#read-form").onsubmit = async e => {
    e.preventDefault();

    const f = fields(e.target);
    const err = $("#read-error");

    err.textContent = "";

    try {
      const r = await api("/sim/read", {
        method: "POST",
        body: {
          gate_id: Number(f.gate_id),
          direction: f.direction,
          uid: f.uid.trim() || null
        }
      });

      gateState = r.gate;

      showVerdict(r);
      drawNet();
      refreshLatest();

    } catch (x) {
      say(err, x.message);
    }
  };

  $("#override-form").onsubmit = async e => {
    e.preventDefault();

    const f = fields(e.target);
    const msg = $("#override-msg");

    try {
      await api("/gate/override", {
        method: "POST",
        body: {
          gate_id: Number($("#read-form [name=gate_id]").value),
          direction: f.direction,
          note: f.note
        }
      });

      say(msg, "Override recorded.", true);

      e.target.reset();
      refreshLatest();

    } catch (x) {
      say(msg, x.message);
    }
  };
}


function showVerdict(r) {
  const cls =
    r.action === "ADMIT" ? "go" :
    r.action === "NO_READ" ? "amber" :
    r.action === "IGNORED" ? "" : "stop";

  const title = {
    ADMIT: "Admitted",
    DENY: "Denied",
    NO_READ: "No tag read",
    IGNORED: "Ignored"
  }[r.action] || r.action;

  $("#verdict").className = "verdict " + cls;

  $("#verdict").innerHTML =
    `<strong>${esc(title)}</strong>${esc(r.reason)}` +
    (r.alerts?.length
      ? `<br><span class="error">Alert: ${r.alerts.map(esc).join(", ")}</span>`
      : "") +
    `<br><span class="muted">
      ${esc(r.mode)} · decided by
      ${r.path === "SERVER" ? "server" : "gate controller"}
      ${r.buzzer ? " · buzzer" : ""}
    </span>`;

  const barrier = $("#barrier");

  barrier.classList.toggle("open", !!r.barrier_open);

  if (r.barrier_open) {
    setTimeout(() => barrier.classList.remove("open"), 3500);
  }
}


function drawNet() {
  const g = gateState;
  const on = g.mode === "ONLINE";

  $("#net").innerHTML = `
    <h3>
      Server link
      <span class="pill ${on ? "" : "off"}">${esc(g.mode)}</span>
    </h3>

    <p class="muted">
      ${esc(g.whitelist_size)} tags on the gate whitelist ·
      ${esc(g.pending)} event(s) waiting to sync.
    </p>

    <div class="row">
      <button id="toggle-net" class="ghost">
        ${on ? "Simulate server outage" : "Restore connection"}
      </button>

      <button id="sync-btn" ${on ? "" : "disabled"}>
        Sync now
      </button>
    </div>

    <p id="net-msg" role="status"></p>
  `;

  $("#toggle-net").onclick = async () => {
    try {
      gateState = await api("/sim/network", {
        method: "POST",
        body: {
          gate_id: 1,
          online: !on
        }
      });

      drawNet();

    } catch (e) {
      say($("#net-msg"), e.message);
    }
  };

  $("#sync-btn").onclick = async () => {
    try {
      const r = await api("/sim/sync", {
        method: "POST",
        body: { gate_id: 1 }
      });

      gateState = r.gate;
      drawNet();

      say($("#net-msg"), `Synced ${r.synced} event(s).`, true);

      refreshLatest();

    } catch (e) {
      say($("#net-msg"), e.message);
    }
  };
}


async function refreshLatest() {
  const rows = await api("/events?limit=8");

  $("#latest").innerHTML = eventsTable(rows);
}


function eventsTable(rows) {
  if (!rows.length) {
    return '<p class="muted">No events yet.</p>';
  }

  return `
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Gate</th>
          <th>Dir</th>
          <th>Plate</th>
          <th>Decision</th>
          <th>Reason</th>
          <th>Source</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(r => `
          <tr>
            <td>${esc(when(r.occurred_at))}</td>
            <td>${esc(r.gate)}</td>
            <td>${esc(r.direction)}</td>
            <td>${esc(r.plate || "")}</td>
            <td>${tag(r.decision)}</td>
            <td>${esc(r.reason)}</td>
            <td>${esc(r.source)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}


/* =========================================
   DASHBOARD
   ========================================= */

async function dashView(v) {
  const d = await api("/dashboard");

  const stat = (n, label) => `
    <div class="card stat">
      <b>${esc(n)}</b>
      <span>${esc(label)}</span>
    </div>
  `;

  v.innerHTML = `
    <h2>Dashboard</h2>

    <div class="grid cols-4">
      ${stat(d.vehicles_inside, "vehicles inside")}
      ${stat(d.registered_vehicles, "registered vehicles")}
      ${stat(d.admitted_today, "admitted today (UTC)")}
      ${stat(d.denied_today, "denied today (UTC)")}
      ${stat(d.open_alerts, "open alerts")}
    </div>

    <div class="card" style="margin-top:1rem">
      <h3>Parking lots</h3>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Lot</th>
              <th>Inside</th>
              <th>Capacity</th>
              <th>Free</th>
            </tr>
          </thead>

          <tbody>
            ${d.lots.map(l => `
              <tr>
                <td>${esc(l.name)}</td>
                <td>${esc(l.current_count)}</td>
                <td>${esc(l.capacity)}</td>
                <td>${Math.max(0, l.capacity - l.current_count)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}


/* =========================================
   VEHICLES AND RFID TAGS
   ========================================= */

async function vehiclesView(v) {
  const rows = await api("/vehicles");
  const admin = user.role === "ADMIN";

  v.innerHTML = `
    <h2>Vehicles and tags</h2>

    ${admin ? `
      <div class="card">
        <h3>Register vehicle</h3>

        <form id="veh-form">
          <div class="row">

            <label>
              Owner name
              <input name="full_name" required>
            </label>

            <label>
              Category
              <select name="category">
                <option>STAFF</option>
                <option>STUDENT</option>
                <option>CONTRACTOR</option>
                <option>OTHER</option>
              </select>
            </label>

            <label>
              Department
              <input name="department">
            </label>

          </div>

          <div class="row">

            <label>
              Plate
              <input name="plate" required>
            </label>

            <label>
              Make / model
              <input name="make_model">
            </label>

            <label>
              Colour
              <input name="colour">
            </label>

            <label>
              Tag UID (optional)
              <input name="uid" placeholder="e.g. E2801160…">
            </label>

            <button type="submit">Register</button>
          </div>

          <p id="veh-msg" role="status"></p>
        </form>
      </div>
    ` : ""}

    <div class="card" style="margin-top:1rem">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Plate</th>
              <th>Owner</th>
              <th>Category</th>
              <th>Status</th>
              <th>Tags</th>
              ${admin ? "<th>Actions</th>" : ""}
            </tr>
          </thead>

          <tbody>
            ${rows.map(r => `
              <tr>
                <td>${esc(r.plate)}</td>
                <td>${esc(r.full_name)}</td>
                <td>${esc(r.category)}</td>
                <td>${tag(r.status)}</td>

                <td>
                  ${r.tags.map(t =>
                    `#${esc(t.tag_id)} ${tag(t.state)}`
                  ).join("<br>") || '<span class="muted">none</span>'}
                </td>

                ${admin ? `
                  <td>
                    <select
                      data-veh="${r.vehicle_id}"
                      aria-label="Vehicle status"
                    >
                      <option ${r.status === "ACTIVE" ? "selected" : ""}>ACTIVE</option>
                      <option ${r.status === "SUSPENDED" ? "selected" : ""}>SUSPENDED</option>
                      <option ${r.status === "BLACKLISTED" ? "selected" : ""}>BLACKLISTED</option>
                    </select>

                    ${r.tags.map(t => `
                      <select
                        data-tag="${t.tag_id}"
                        aria-label="Tag ${t.tag_id} state"
                      >
                        <option ${t.state === "ACTIVE" ? "selected" : ""}>ACTIVE</option>
                        <option ${t.state === "SUSPENDED" ? "selected" : ""}>SUSPENDED</option>
                        <option ${t.state === "REVOKED" ? "selected" : ""}>REVOKED</option>
                      </select>
                    `).join("")}

                    <button
                      type="button"
                      class="small ghost"
                      data-addtag="${r.vehicle_id}"
                    >Add tag</button>
                  </td>
                ` : ""}
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;

  if (!admin) return;

  $("#veh-form").onsubmit = async e => {
    e.preventDefault();

    const f = fields(e.target);
    const msg = $("#veh-msg");

    try {
      const r = await api("/vehicles", {
        method: "POST",
        body: {
          plate: f.plate,
          make_model: f.make_model,
          colour: f.colour,
          owner: {
            full_name: f.full_name,
            category: f.category,
            department: f.department
          }
        }
      });

      if (f.uid.trim()) {
        await api(`/vehicles/${r.vehicle_id}/tags`, {
          method: "POST",
          body: { uid: f.uid.trim() }
        });
      }

      go("vehicles");

    } catch (x) {
      say(msg, x.message);
    }
  };

  v.onchange = async e => {
    const t = e.target;

    try {
      if (t.dataset.veh) {
        await api("/vehicles/" + t.dataset.veh, {
          method: "PATCH",
          body: { status: t.value }
        });
      }

      if (t.dataset.tag) {
        await api("/tags/" + t.dataset.tag, {
          method: "PATCH",
          body: { state: t.value }
        });
      }

    } catch (x) {
      alert(x.message);
      go("vehicles");
    }
  };

  v.onclick = async e => {
    const id = e.target.dataset?.addtag;

    if (!id) return;

    const uid = prompt(
      "Tag UID (hex). Leave blank to generate a random one:",
      ""
    );

    if (uid === null) return;

    const use = uid.trim() || randomUid();

    try {
      await api(`/vehicles/${id}/tags`, {
        method: "POST",
        body: { uid: use }
      });

      alert(
        "Tag issued. UID: " + use +
        "\nNote it down: only a hash is stored."
      );

      go("vehicles");

    } catch (x) {
      alert(x.message);
    }
  };
}


/* =========================================
   VISITOR PASSES
   ========================================= */

async function visitorsView(v) {
  const rows = await api("/visitor-passes");

  const pad = n => String(n).padStart(2, "0");

  const d = new Date();

  const local = x =>
    `${x.getFullYear()}-${pad(x.getMonth() + 1)}-${pad(x.getDate())}` +
    `T${pad(x.getHours())}:${pad(x.getMinutes())}`;

  const end = new Date(d.getTime() + 4 * 3600e3);

  v.innerHTML = `
    <h2>Visitor passes</h2>

    <div class="card">
      <form id="pass-form">

        <div class="row">
          <label>
            Visitor
            <input name="visitor_name" required>
          </label>

          <label>
            Plate
            <input name="plate" required>
          </label>

          <label>
            Host
            <input name="host">
          </label>
        </div>

        <div class="row">
          <label>
            Loan tag UID
            <input name="uid" required value="${randomUid()}">
          </label>

          <label>
            Valid from
            <input
              type="datetime-local"
              name="valid_from"
              value="${local(d)}"
              required
            >
          </label>

          <label>
            Valid until
            <input
              type="datetime-local"
              name="valid_until"
              value="${local(end)}"
              required
            >
          </label>

          <button type="submit">Issue pass</button>
        </div>

        <p id="pass-msg" role="status"></p>
      </form>
    </div>

    <div class="card" style="margin-top:1rem">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Visitor</th>
              <th>Plate</th>
              <th>Host</th>
              <th>Valid from</th>
              <th>Valid until</th>
              <th>State</th>
              <th></th>
            </tr>
          </thead>

          <tbody>
            ${rows.map(r => `
              <tr>
                <td>${esc(r.visitor_name)}</td>
                <td>${esc(r.plate)}</td>
                <td>${esc(r.host)}</td>
                <td>${esc(when(r.valid_from))}</td>
                <td>${esc(when(r.valid_until))}</td>
                <td>${tag(r.state)}</td>

                <td>
                  ${r.state === "ACTIVE" ? `
                    <button
                      type="button"
                      class="small ghost"
                      data-cancel="${r.pass_id}"
                    >Cancel</button>
                  ` : ""}
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;

  $("#pass-form").onsubmit = async e => {
    e.preventDefault();

    const f = fields(e.target);
    const msg = $("#pass-msg");

    try {
      await api("/visitor-passes", {
        method: "POST",
        body: {
          ...f,
          valid_from: isoLocalToUtc(f.valid_from),
          valid_until: isoLocalToUtc(f.valid_until)
        }
      });

      go("visitors");

    } catch (x) {
      say(msg, x.message);
    }
  };

  v.onclick = async e => {
    const id = e.target.dataset?.cancel;

    if (!id) return;

    try {
      await api(`/visitor-passes/${id}/cancel`, {
        method: "POST"
      });

      go("visitors");

    } catch (x) {
      alert(x.message);
    }
  };
}


/* =========================================
   ALERTS
   ========================================= */

async function alertsView(v) {
  const rows = await api("/alerts");
  const canAck = ["ADMIN", "SECURITY"].includes(user.role);

  v.innerHTML = `
    <h2>Alerts</h2>

    <div class="card">
      <div class="table-wrap">

        ${rows.length ? `
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Type</th>
                <th>Message</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>

            <tbody>
              ${rows.map(r => `
                <tr>
                  <td>${esc(when(r.created_at))}</td>
                  <td>${esc(r.type)}</td>
                  <td>${esc(r.message)}</td>
                  <td>
                    ${tag(r.status)}
                    ${r.acknowledged_by
                      ? " by " + esc(r.acknowledged_by)
                      : ""}
                  </td>

                  <td>
                    ${canAck && r.status === "OPEN" ? `
                      <button
                        type="button"
                        class="small"
                        data-ack="${r.alert_id}"
                      >Acknowledge</button>
                    ` : ""}
                  </td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        ` : '<p class="muted">No alerts.</p>'}

      </div>
    </div>
  `;

  v.onclick = async e => {
    const id = e.target.dataset?.ack;

    if (!id) return;

    try {
      await api(`/alerts/${id}/ack`, {
        method: "POST"
      });

      go("alerts");

    } catch (x) {
      alert(x.message);
    }
  };
}


/* =========================================
   EVENTS AND REPORTS
   ========================================= */

async function eventsView(v) {
  v.innerHTML = `
    <h2>Events and reports</h2>

    <div class="card">
      <form id="ev-form">
        <div class="row">

          <label>
            From (UTC date)
            <input type="date" name="start">
          </label>

          <label>
            To (UTC date, exclusive)
            <input type="date" name="end">
          </label>

          <label>
            Decision
            <select name="decision">
              <option value="">All</option>
              <option>ADMITTED</option>
              <option>DENIED</option>
            </select>
          </label>

          <button type="submit">Filter</button>

          <button type="button" id="csv" class="ghost">
            Download CSV
          </button>

        </div>
      </form>
    </div>

    <div class="card" style="margin-top:1rem">
      <div class="table-wrap" id="ev-table"></div>
    </div>
  `;

  const queryString = () => {
    const p = new URLSearchParams(
      Object.entries(fields($("#ev-form")))
        .filter(([, value]) => value)
    );

    if (p.get("start")) {
      p.set("start", p.get("start") + "T00:00:00");
    }

    if (p.get("end")) {
      p.set("end", p.get("end") + "T00:00:00");
    }

    return p.toString();
  };

  const load = async () => {
    try {
      $("#ev-table").innerHTML = eventsTable(
        await api("/events?limit=200&" + queryString())
      );
    } catch (e) {
      $("#ev-table").innerHTML =
        `<p class="error">${esc(e.message)}</p>`;
    }
  };

  $("#ev-form").onsubmit = e => {
    e.preventDefault();
    load();
  };

  $("#csv").onclick = () => {
    const f = fields($("#ev-form"));
    const p = new URLSearchParams();

    if (f.start) {
      p.set("start", f.start + "T00:00:00");
    }

    if (f.end) {
      p.set("end", f.end + "T00:00:00");
    }

    if (f.decision) {
      p.set("decision", f.decision);
    }

    location.href = "/api/reports/events.csv?" + p.toString();
  };

  load();
}


/* =========================================
   USERS AND AUDIT LOG
   ========================================= */

async function adminView(v) {
  const [users, audit] = await Promise.all([
    api("/users"),
    api("/audit")
  ]);

  v.innerHTML = `
    <h2>Users and audit log</h2>

    <div class="grid cols-2">

      <div class="card">
        <h3>Create account</h3>

        <form id="user-form">

          <label>
            Username
            <input name="username" required>
          </label>

          <label>
            Password (min 8)
            <input
              name="password"
              type="password"
              minlength="8"
              autocomplete="new-password"
              required
            >
          </label>

          <label>
            Role
            <select name="role">
              <option>SECURITY</option>
              <option>ICT</option>
              <option>ADMIN</option>
            </select>
          </label>

          <button type="submit">Create</button>

          <p id="user-msg" role="status"></p>
        </form>
      </div>

      <div class="card">
        <h3>Accounts</h3>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Active</th>
              </tr>
            </thead>

            <tbody>
              ${users.map(u => `
                <tr>
                  <td>${esc(u.username)}</td>
                  <td>${esc(u.role)}</td>
                  <td>
                    <input
                      type="checkbox"
                      data-user="${u.user_id}"
                      ${u.active ? "checked" : ""}
                      aria-label="Active: ${esc(u.username)}"
                      style="width:auto"
                    >
                  </td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </div>

    </div>

    <div class="card" style="margin-top:1rem">
      <h3>Audit log</h3>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>User</th>
              <th>Action</th>
              <th>Detail</th>
            </tr>
          </thead>

          <tbody>
            ${audit.map(a => `
              <tr>
                <td>${esc(when(a.at))}</td>
                <td>${esc(a.username)}</td>
                <td>${esc(a.action)}</td>
                <td>${esc(a.detail)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;

  $("#user-form").onsubmit = async e => {
    e.preventDefault();

    const msg = $("#user-msg");

    try {
      await api("/users", {
        method: "POST",
        body: fields(e.target)
      });

      go("admin");

    } catch (x) {
      say(msg, x.message);
    }
  };

  v.onchange = async e => {
    const id = e.target.dataset?.user;

    if (!id) return;

    try {
      await api("/users/" + id, {
        method: "PATCH",
        body: { active: e.target.checked }
      });

    } catch (x) {
      alert(x.message);
      go("admin");
    }
  };
}


/* =========================================
   APPLICATION EVENT HANDLERS
   ========================================= */

// One delegated click handler handles all generated tabs.
$("#tabs").addEventListener("click", e => {
  const button = e.target.closest("button[data-tab]");

  if (!button || !$("#tabs").contains(button)) return;

  const name = button.dataset.tab;

  closeMobileNav();
  go(name);
});


// Sign out.

async function logoutUser() {
  try {
    await api("/auth/logout", {
      method: "POST"
    });

    showLogin();

  } catch (e) {
    if (user) {
      alert(e.message);
    }
  }
}

// Desktop sidebar logout
$("#logout")?.addEventListener("click", logoutUser);

// Mobile header logout
$("#mobile-logout")?.addEventListener("click", logoutUser);

// Sign in.
$("#login-form").addEventListener("submit", async e => {
  e.preventDefault();

  const err = $("#login-error");
  const submit = e.target.querySelector('[type="submit"]');

  err.textContent = "";

  if (submit) {
    submit.disabled = true;
  }

  try {
    user = await api("/auth/login", {
      method: "POST",
      body: fields(e.target)
    });

    e.target.reset();

    showApp();

  } catch (x) {
    err.textContent = x.message;

  } finally {
    if (submit) {
      submit.disabled = false;
    }
  }
});


/* =========================================
   APPLICATION STARTUP
   ========================================= */

(async function boot() {
  try {
    user = await api("/auth/me");
    showApp();

  } catch {
    showLogin();
  }
})();