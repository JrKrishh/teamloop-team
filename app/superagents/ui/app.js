"use strict";
// Super Agents UI. Text that comes from teammates or the model (titles, summaries, answers) is untrusted:
// it goes in with textContent only. innerHTML is used only for this file's own icons and marks.

const $ = id => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const HASH = new URLSearchParams(location.hash.slice(1));  // k: the per-launch key from the app window; view/ask: screenshots
const KEY = (() => {
  const k = HASH.get("k") || sessionStorage.getItem("sa-key");
  if (k) sessionStorage.setItem("sa-key", k);
  history.replaceState(null, "", "/");
  return k || "";
})();
const S = {boot: null, user: null, teams: [], team: null, board: null, laptop: null, view: "chat", events: 0,
  mode: "manual", model: "auto", files: []};
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

async function api(path, {method = "GET", body} = {}) {
  const headers = {"X-App-Key": KEY};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const r = await fetch(path, {method, headers, body: body !== undefined ? JSON.stringify(body) : undefined});
  let data = {};
  try { data = await r.json(); } catch (e) { /* empty */ }
  if (!r.ok) { const e = new Error(typeof data.detail === "string" ? data.detail : "Something went wrong. Try again."); e.status = r.status; throw e; }
  return data;
}
const hub = (path, opts) => api(`/api/cloud/${path}`, opts);
const withTeam = path => `${path}${path.includes("?") ? "&" : "?"}team=${encodeURIComponent(S.team)}`;
const team = () => S.teams.find(t => t.id === S.team) || null;

// ---- icons and marks ---------------------------------------------------------------------------------
const ICONS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  spark: '<path d="M12 3.5c.6 3.9 2.6 5.9 6.5 6.5-3.9.6-5.9 2.6-6.5 6.5-.6-3.9-2.6-5.9-6.5-6.5 3.9-.6 5.9-2.6 6.5-6.5Z"/><path d="M19 15.5c.25 1.6 1 2.35 2.5 2.5-1.5.25-2.25 1-2.5 2.5-.25-1.5-1-2.25-2.5-2.5 1.5-.15 2.25-.9 2.5-2.5Z"/>',
  board: '<rect x="3.5" y="4" width="7" height="16" rx="2"/><rect x="13.5" y="4" width="7" height="9" rx="2"/><path d="M13.5 17h7"/>',
  team: '<circle cx="9" cy="8.5" r="3.2"/><path d="M3.5 19.5c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5"/><circle cx="17" cy="9.5" r="2.4"/><path d="M15.6 14.7c2.3.1 4.2 1.6 4.9 4.8"/>',
  laptop: '<rect x="4.5" y="5" width="15" height="10.5" rx="1.8"/><path d="M2.5 19h19"/>',
  dots: '<circle cx="6" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18" cy="12" r="1.2"/>',
  moon: '<path d="M19.5 14.5A7.5 7.5 0 0 1 9.5 4.5a7.5 7.5 0 1 0 10 10Z"/>',
  sunny: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
  out: '<path d="M14 4.5h3.5a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H14"/><path d="M10 8l-4 4 4 4M6 12h9.5"/>',
  chev: '<path d="m7 10 5 5 5-5"/>',
  up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  sun: '<path d="M4 17h16"/><path d="M7 17a5 5 0 0 1 10 0"/><path d="M12 6.5v2M5.6 9.6 7 11M18.4 9.6 17 11"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  folder: '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  flag: '<path d="M5.5 21V4.5M5.5 5h11l-2 4 2 4h-11"/>',
  bolt: '<path d="M13 3 5.5 13.5H12L11 21l7.5-10.5H12Z"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  send: '<path d="M4 12h12M12 6l6 6-6 6"/>',
  file: '<path d="M14 3.5H7.5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8Z"/><path d="M14 3.5V8h4.5M9 13h6M9 16.5h4"/>',
  github: '<path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21"/>',
  chip: '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/><path d="M9.5 3v3.5M14.5 3v3.5M9.5 17.5V21M14.5 17.5V21M3 9.5h3.5M3 14.5h3.5M17.5 9.5H21M17.5 14.5H21"/>',
  hand: '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V11M11 10.5V4a1.5 1.5 0 0 1 3 0v6.5M14 10.5V5.5a1.5 1.5 0 0 1 3 0V14a6 6 0 0 1-6 6h-.6a6 6 0 0 1-4.6-2.2L3.6 15a1.5 1.5 0 0 1 2.3-1.9L8 15"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6h.01M4 12h.01M4 18h.01" stroke-width="3"/>',
  play: '<path d="M7 5.5v13l11-6.5Z"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/>',
};
// Like Claude Code's modes: Shift+Tab cycles them.
const MODES = {
  manual: {label: "Manual", icon: "hand", desc: "Agent S asks before each change to the board.", short: "Asks before each change"},
  auto: {label: "Auto", icon: "bolt", desc: "Agent S makes routine changes itself and tells you. You can undo them.", short: "Makes routine changes itself"},
  plan: {label: "Plan", icon: "list", desc: "Agent S writes a plan first. Nothing changes until you run it.", short: "Writes a plan; you run it"},
};
const MODE_ORDER = ["manual", "auto", "plan"];
const MODELS = {
  auto: {label: "Auto", desc: "Super for answers, Ultra for plans and imports"},
  lightning: {label: "Nemotron Lightning", desc: "Fastest replies"},
  super: {label: "Nemotron Super", desc: "Balanced · 120B"},
  ultra: {label: "Nemotron Ultra", desc: "Deepest reasoning · 550B"},
};
const MAX_FILES = 5, MAX_FILE_BYTES = 200_000;
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg>`;
function paintIcons(root = document) { root.querySelectorAll(".ic[data-ic]").forEach(n => { if (!n.firstElementChild) n.innerHTML = icon(n.dataset.ic); }); }
function ic(name) { const s = el("span", "ic"); s.innerHTML = icon(name); return s; }

const HOOD = "M50 95C30 95 14 93 11 86C8.5 80 9 68 9.5 56C11 31 27 14 48 12.5C56 12 63 9.5 70 3.5C71.2 9.5 69.8 14.5 66.5 17.8C81 25 90 39 90.5 56C91 68 91.5 80 89 86C86 93 70 95 50 95Z";
function agent(cls = "", hood = "") {
  const t = document.createElement("template");
  t.innerHTML = `<svg class="agent ${cls}" viewBox="0 0 100 100" aria-hidden="true"${hood ? ` style="--hood:${hood}"` : ""}><path class="hood" d="${HOOD}"/>`
    + '<ellipse class="face" cx="50" cy="61" rx="30" ry="27"/><g class="eyes"><ellipse class="eye" cx="38.5" cy="62" rx="6.2" ry="7.8"/>'
    + '<ellipse class="eye" cx="61.5" cy="62" rx="6.2" ry="7.8"/><circle class="glint" cx="40.9" cy="58.6" r="2.1"/><circle class="glint" cx="63.9" cy="58.6" r="2.1"/></g></svg>';
  return t.content.firstElementChild;
}
const COLOURS = ["green", "pink", "purple", "orange", "olive"];
function colour(name) { let h = 0; for (const c of name || "") h = (h * 31 + c.charCodeAt(0)) >>> 0; return COLOURS[h % COLOURS.length]; }
function mascot(name, pose) { const i = el("img"); i.src = `/ui/mascot/${colour(name)}/${pose}.webp`; i.alt = ""; return i; }
const TOOLS = {claude_code: "Claude Code", codex: "Codex", cursor: "Cursor"};
function ago(t) { const s = Math.max(0, Date.now() / 1000 - t); return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`; }
function clock(ts) { if (!ts) return ""; const d = new Date(ts); return isNaN(d) ? ts.slice(11, 16) : d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", hour12: false}); }
function toast(text, bad) { const t = el("div", "toast" + (bad ? " bad" : ""), text); $("toasts").append(t); setTimeout(() => t.remove(), 4200); }

// ---- theme ----------------------------------------------------------------------------------------
function setTheme(theme, save = true) {
  document.documentElement.dataset.theme = theme;
  $("themeLabel").textContent = theme === "dark" ? "Light theme" : "Dark theme";
  const t = $("themeBtn").querySelector(".ic"); t.dataset.ic = theme === "dark" ? "sunny" : "moon"; t.innerHTML = icon(t.dataset.ic);
  api("/api/window/theme", {method: "POST", body: {dark: theme === "dark"}}).catch(() => {});
  if (save) api("/api/prefs", {method: "POST", body: {theme}}).catch(() => {});
}

// ---- screens ----------------------------------------------------------------------------------------
function show(id) { for (const s of ["login", "onboard", "shell"]) $(s).hidden = s !== id; }

async function start() {
  paintIcons();
  const splash = new Promise(r => setTimeout(r, REDUCED ? 150 : 2150));
  let boot = null;
  try { boot = await api("/api/boot"); } catch (e) { /* shown below */ }
  await splash;
  $("splash").classList.add("out");
  setTimeout(() => $("splash").remove(), 520);
  if (!boot) { showLogin(); $("loginErr").textContent = "Super Agents couldn't start its local service. Restart the app."; return; }
  applyBoot(boot);
}

function applyBoot(boot) {
  S.boot = boot;
  setTheme((boot.prefs || {}).theme || "dark", false);
  setMode((boot.prefs || {}).mode || "manual", false);
  setModel((boot.prefs || {}).model || "auto", false);
  if (!boot.signed_in) return showLogin();
  S.user = boot.user; S.teams = boot.teams; S.team = boot.team; S.laptop = boot.laptop;
  if (boot.offline) toast(boot.offline, true);
  if (!S.teams.length) return showOnboard();
  showShell();
}

async function reboot() { applyBoot(await api("/api/boot")); }

// ---- sign in ------------------------------------------------------------------------------------------
let signUp = false, waitTimer = null, lastAuthUrl = "";
function showLogin() {
  show("login");
  const cast = $("loginCast");
  if (!cast.childElementCount) {
    for (const [hood, size] of [["#3E9B6B", 92], ["#C2554C", 128], ["#8E6BD8", 92]]) {
      const a = agent("", hood); a.setAttribute("width", size); a.setAttribute("height", size);
      const w = el("span", "bob"); w.append(a); cast.append(w);
    }
  }
  $("loginForm").hidden = false; $("loginWait").hidden = true;
}
$("modeBtn").onclick = () => {
  signUp = !signUp;
  $("nameField").hidden = !signUp;
  $("emailBtn").textContent = signUp ? "Create account" : "Sign in";
  $("modeBtn").textContent = signUp ? "Have an account? Sign in" : "New here? Create an account";
  $("pwIn").autocomplete = signUp ? "new-password" : "current-password";
  $("loginErr").textContent = "";
};
$("emailForm").addEventListener("submit", async ev => {
  ev.preventDefault();
  const btn = $("emailBtn"); btn.disabled = true; $("loginErr").textContent = "";
  try {
    const r = await api("/api/auth/email", {method: "POST", body: {email: $("emailIn").value.trim(), password: $("pwIn").value,
      mode: signUp ? "signup" : "signin", name: $("nameIn").value.trim()}});
    if (r.confirm) { $("loginErr").textContent = "Check your inbox to confirm your email, then sign in here."; }
    else { $("pwIn").value = ""; await reboot(); }
  } catch (e) { $("loginErr").textContent = e.message; }
  btn.disabled = false;
});
$("githubBtn").onclick = async () => {
  $("loginErr").textContent = "";
  try {
    lastAuthUrl = (await api("/api/auth/github", {method: "POST"})).url;
    $("loginForm").hidden = true; $("loginWait").hidden = false; $("waitErr").textContent = "";
    const art = $("loginWait").querySelector(".wait-art"); art.replaceChildren(agent("thinking"));
    clearInterval(waitTimer);
    waitTimer = setInterval(async () => {
      const st = await api("/api/auth/status").catch(() => ({}));
      if (st.state === "done") { clearInterval(waitTimer); await reboot(); }
      else if (st.state === "error") { clearInterval(waitTimer); $("waitErr").textContent = st.error || "Sign-in didn't finish."; }
    }, 1000);
  } catch (e) { $("loginErr").textContent = e.message; }
};
$("reopenBtn").onclick = () => { if (lastAuthUrl) $("githubBtn").click(); };
$("cancelBtn").onclick = async () => { clearInterval(waitTimer); await api("/api/auth/cancel", {method: "POST"}).catch(() => {}); showLogin(); };

// ---- first run ----------------------------------------------------------------------------------------
let onboardBack = false;
function showOnboard(back = false) {
  onboardBack = back;
  show("onboard");
  const head = $("onboardHead"); head.replaceChildren();
  const a = agent(); a.setAttribute("width", 72); a.setAttribute("height", 72);
  const first = (S.user && S.user.name || "").split(" ")[0];
  head.append(a, el("h1", null, back ? "Another team" : `Welcome, ${first}.`),
    el("p", "sub", back ? "Start a new team or join one with a link." : "Set up your team. This laptop starts reporting to it straight away."));
  if (back) { const b = el("button", "link", "Back to Super Agents"); b.type = "button"; b.onclick = showShell; head.append(b); }
  for (const art of document.querySelectorAll(".choice-art")) {
    if (art.childElementCount) continue;
    const cast = art.dataset.art === "create" ? [["#C2554C", 64]] : [["#3E9B6B", 50], ["#C2554C", 64], ["#8E6BD8", 50]];
    for (const [hood, n] of cast) { const m = agent("", hood); m.setAttribute("width", n); m.setAttribute("height", n); art.append(m); }
  }
  $("onboardErr").textContent = "";
}
async function joinedTeam(t, verb) {
  S.team = t.id;
  await api("/api/team", {method: "POST", body: {team: t.id}});
  try { await api("/api/laptop/team", {method: "POST", body: {team: t.id}}); }
  catch (e) { toast(`${verb}, but this laptop isn't connected yet: ${e.message}`, true); }
  await reboot();
  toast(`${verb} ${t.name}. This laptop reports to it now.`);
}
$("createForm").addEventListener("submit", async ev => {
  ev.preventDefault();
  const btn = ev.submitter || $("createForm").querySelector("button"); btn.disabled = true;
  try { await joinedTeam(await hub("teams", {method: "POST", body: {name: $("teamNameIn").value.trim()}}), "Created"); $("teamNameIn").value = ""; }
  catch (e) { $("onboardErr").textContent = e.message; }
  btn.disabled = false;
});
$("joinForm").addEventListener("submit", async ev => {
  ev.preventDefault();
  const btn = ev.submitter || $("joinForm").querySelector("button"); btn.disabled = true;
  const raw = $("inviteIn").value.trim();
  const tok = (raw.match(/(inv_[A-Za-z0-9_-]+)/) || [])[1];
  try {
    if (!tok) throw new Error("That doesn't look like an invite link. It contains inv_…");
    const r = await hub(`invites/${tok}/accept`, {method: "POST", body: {}});
    await joinedTeam(r.team, "Joined"); $("inviteIn").value = "";
  } catch (e) { $("onboardErr").textContent = e.message; }
  btn.disabled = false;
});

// ---- the shell ------------------------------------------------------------------------------------------
let pollTimer = null;
function showShell() {
  show("shell");
  $("railMark").replaceChildren(agent());
  $("meName").textContent = S.user.name;
  $("meRole").textContent = team() ? `${team().role === "lead" ? "Lead" : "Member"} · ${team().name}` : "";
  const av = $("meAvatar"); av.replaceChildren();
  if (S.user.avatar) { const i = el("img"); i.src = S.user.avatar; i.alt = ""; av.append(i); } else av.textContent = (S.user.name || "?").slice(0, 1).toUpperCase();
  $("versionLine").textContent = `Super Agents ${S.boot.version}`;
  $("teamName").textContent = team() ? team().name : "Pick a team";
  renderLaptopChip();
  if (!$("thread").childElementCount) renderHello();
  go(HASH.get("view") || S.view);
  HASH.delete("view");
  loadBoard().then(() => { if (HASH.get("ask")) { ask(HASH.get("ask")); HASH.delete("ask"); } });
  clearInterval(pollTimer);
  pollTimer = setInterval(() => { if (!document.hidden) { loadBoard(); refreshLaptop(); } }, 20000);
}
function go(view) {
  S.view = view;
  for (const b of document.querySelectorAll("#nav button")) b.classList.toggle("on", b.dataset.view === view);
  for (const v of ["chat", "board", "team", "laptop"]) $(`view-${v}`).hidden = v !== view;
  if (view === "board") renderBoard();
  if (view === "team") loadTeam();
  if (view === "laptop") refreshLaptop(true);
  if (view === "chat") setTimeout(() => $("askIn").focus(), 50);
}
for (const b of document.querySelectorAll("#nav button")) b.onclick = () => go(b.dataset.view);
$("laptopChip").onclick = () => go("laptop");
$("newChat").onclick = () => { $("thread").replaceChildren(); renderHello(); go("chat"); };
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { closeMenus(); if (!$("drawer").hidden) closeTask(); }
  if (e.ctrlKey && e.key.toLowerCase() === "n" && !$("shell").hidden) { e.preventDefault(); $("newChat").click(); }
});

function closeMenus() {
  for (const id of ["meMenu", "teamMenu", "importMenu", "modeMenu", "modelMenu"]) $(id).hidden = true;
  document.querySelectorAll('[aria-expanded="true"]').forEach(b => b.setAttribute("aria-expanded", "false"));
}
document.addEventListener("click", e => { if (!e.target.closest(".menu, #meBtn, #teamBtn, .cwrap")) closeMenus(); });
$("meBtn").onclick = () => { const m = $("meMenu"); const open = m.hidden; closeMenus(); m.hidden = !open; };
$("themeBtn").onclick = () => { setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"); closeMenus(); };
$("signOutBtn").onclick = async () => {
  closeMenus(); clearInterval(pollTimer);
  await api("/api/auth/signout", {method: "POST"}).catch(() => {});
  S.user = null; S.board = null; $("thread").replaceChildren();
  await reboot();
};
$("teamBtn").onclick = () => {
  const m = $("teamMenu"); const open = m.hidden; closeMenus(); if (!open) return;
  m.replaceChildren();
  for (const t of S.teams) {
    const b = el("button", t.id === S.team ? "on" : null); b.type = "button";
    b.append(ic(t.id === S.team ? "check" : "team"), el("span", null, t.name), el("small", null, t.role === "lead" ? " · lead" : ""));
    b.onclick = async () => { closeMenus(); if (t.id === S.team) return; S.team = t.id; S.board = null; await api("/api/team", {method: "POST", body: {team: t.id}}); $("thread").replaceChildren(); showShell(); };
    m.append(b);
  }
  m.append(el("hr"));
  const add = el("button"); add.type = "button"; add.append(ic("plus"), el("span", null, "Start or join another team"));
  add.onclick = () => { closeMenus(); showOnboard(true); };
  m.append(add);
  m.hidden = false;
};

function renderLaptopChip() {
  const c = $("laptopChip"); const L = S.laptop || {}; c.replaceChildren(el("i"));
  const here = L.team && L.team.id === S.team;
  if (!L.team) { c.className = "status-chip warn"; c.append("This laptop isn't connected"); }
  else if (L.paused) { c.className = "status-chip warn"; c.append("Sharing paused"); }
  else if (!here) { c.className = "status-chip"; c.append(`This laptop reports to ${L.team.name}`); }
  else { c.className = "status-chip ok"; const n = (L.repos || []).filter(r => r.ok).length; c.append(`Reporting · ${n} repo${n === 1 ? "" : "s"}`); }
}
async function refreshLaptop(render) {
  try { S.laptop = await api("/api/laptop"); renderLaptopChip(); if (render || S.view === "laptop") renderLaptop(); } catch (e) { /* next turn */ }
}

// ---- board data ------------------------------------------------------------------------------------------
let refreshedAt = 0;
async function loadBoard() {
  if (!S.team) return;
  try {
    S.board = await hub(withTeam("board"));
    S.events = S.board.tasks.reduce((n, t) => n + (t.events || 0), 0);
    renderLive();
    if (S.view === "board") renderBoard();
    if (Date.now() - refreshedAt > 30000) {  // Agent S re-estimates stale tasks; the board never waits for it
      refreshedAt = Date.now();
      hub(withTeam("refresh"), {method: "POST", body: {}}).then(r => { if (r.updated) loadBoard(); }).catch(() => {});
    }
  } catch (e) { if (e.status === 401) { await reboot(); } }
}
function renderLive() {
  const ul = $("liveList"); ul.replaceChildren();
  const people = (S.board ? S.board.members : []).slice().sort((a, b) => b.last_activity - a.last_activity);
  const live = people.filter(p => p.active);
  for (const p of (live.length ? live : people.slice(0, 4))) {
    const li = el("li"); li.append(mascot(p.name, p.active ? "idle" : "sleep"), el("span", null, p.name));
    li.title = p.active ? "active in the last 5 minutes" : `last seen ${ago(p.last_activity)}`; ul.append(li);
  }
  if (!people.length) ul.append(el("li", "none", "Nobody has reported yet."));
}

// ---- chat ------------------------------------------------------------------------------------------------
function greeting() { const h = new Date().getHours(); return h < 5 ? "Up late" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; }
function renderHello() {
  const t = $("thread"); t.replaceChildren();
  const box = el("div", "hello"); const a = agent();
  const first = (S.user && S.user.name || "").split(" ")[0];
  box.append(a, el("h1", null, `${greeting()}, ${first}.`),
    el("p", null, "Ask Agent S about your team's work. Every answer points to the session events it comes from."));
  const ideas = [["flag", "What's blocked right now?", "Blockers, with the sessions that show them"],
    ["check", "What did the team finish today?", "Done means a merged PR, passing tests or a commit"],
    ["list", "Plan our next tasks and suggest owners", "Proposes changes to the board; you approve them"],
    ["sun", "Write today's digest", "Shipped, in progress, blocked, at risk"]];
  const grid = el("div", "suggest");
  for (const [i, text, small] of ideas) {
    const b = el("button"); b.type = "button";
    const words = el("span", null, text); words.append(el("small", null, small));
    b.append(ic(i), words);
    b.onclick = () => (i === "sun" ? digest() : ask(text));
    grid.append(b);
  }
  box.append(grid, el("p", "tip", "Tip: + imports a spec or a repo's GitHub issues for Agent S to plan from. Shift+Tab switches mode."));
  t.append(box);
}
function fileChip(name, size, onRemove) {
  const c = el("span", "fchip"); c.append(ic("file"), el("span", null, name));
  if (size != null) c.append(el("small", null, size >= 1024 ? `${Math.round(size / 1024)} KB` : `${size} B`));
  if (onRemove) { const x = el("button"); x.type = "button"; x.setAttribute("aria-label", `Remove ${name}`); x.append(ic("x")); x.onclick = onRemove; c.append(x); }
  return c;
}
function userMsg(text, files) {
  const t = $("thread"); const hello = t.querySelector(".hello"); if (hello) hello.remove();
  const m = el("div", "msg user"); const col = el("div", "stack-r"); col.append(el("div", "bubble", text));
  if (files && files.length) { const f = el("div", "files"); for (const x of files) f.append(fileChip(x.name)); col.append(f); }
  m.append(col); t.append(m); scrollDown();
}
function agentMsg() {
  const m = el("div", "msg agent"); const body = el("div", "body");
  const who = el("div", "who"); who.append("Agent S");
  const doing = S.mode === "plan" ? "Planning" : "Reading";
  const line = el("div", "thinking-line", S.events ? `${doing} from ${S.events} session events…` : `${doing} the team's sessions…`);
  body.append(who, line); m.append(agent("thinking"), body); $("thread").append(m); scrollDown();
  return {m, body, who, line};
}
function scrollDown() { const t = $("thread"); requestAnimationFrame(() => t.scrollTo({top: t.scrollHeight, behavior: REDUCED ? "auto" : "smooth"})); }
function settle(slot, meta) { slot.m.querySelector(".agent").classList.remove("thinking"); slot.line.remove(); if (meta) slot.who.append(el("small", null, meta)); }
const shortModel = m => /ultra/i.test(m || "") ? "Nemotron Ultra" : /super/i.test(m || "") ? "Nemotron Super"
  : /lightning/i.test(m || "") ? "Nemotron Lightning" : (m || "").replace(/^ollama:/, "local ");
const titleOf = task => ((S.board ? S.board.tasks : []).find(t => t.task === task) || {}).title || "";

async function ask(q) {
  if (!S.team || !q) return;
  const files = S.files.splice(0); renderChips();
  userMsg(q, files);
  const slot = agentMsg();
  $("askBtn").disabled = true;
  try {
    const r = await hub(withTeam("agent"), {method: "POST", body: {message: q, mode: S.mode, model: S.model,
      attachments: files.map(f => ({name: f.name, text: f.text}))}});
    settle(slot, `${shortModel(r.model)} · ${MODES[r.mode].label}`);
    const cited = r.citations || [];
    if (r.kind === "work" && !cited.length) slot.m.classList.add("none");
    slot.body.append(el("div", "answer", r.answer));
    if (cited.length || r.kind === "work") {
      const row = el("div", "row gap");
      row.append(el("span", "badge " + (cited.length ? "ok" : "none"), cited.length ? `${cited.length} event${cited.length > 1 ? "s" : ""} cited` : "No evidence"));
      if (cited.length) {
        const b = el("button", "evidence-btn", "Show evidence"); b.type = "button";
        b.onclick = () => toggleEvidence(slot.body, cited, b);
        row.append(b);
        if (HASH.get("evidence")) { HASH.delete("evidence"); setTimeout(() => b.click(), 50); }
      }
      slot.body.append(row);
    }
    if (r.plan && r.plan.length) {
      const box = el("div", "plan-box"); box.append(el("div", "label", "Plan")); const ol = el("ol");
      for (const step of r.plan) ol.append(el("li", null, step));
      box.append(ol); slot.body.append(box);
    }
    if (r.actions && r.actions.length) renderActions(slot.body, r.actions, r.mode);
  } catch (e) { settle(slot); slot.m.classList.add("none"); slot.body.append(el("div", "answer", e.message)); }
  $("askBtn").disabled = false; scrollDown();
}
async function toggleEvidence(body, ids, btn) {
  const open = body.querySelector(".evidence");
  if (open) { open.remove(); btn.textContent = "Show evidence"; return; }
  btn.disabled = true;
  try {
    const r = await hub(withTeam(`events?ids=${ids.join(",")}`));
    const box = el("div", "evidence");
    for (const e of r.events) {
      const row = el("div", "ev"); const text = el("div");
      text.append(el("span", "who-chip", e.member || ""), e.line || e.kind);
      row.append(el("time", null, clock(e.ts)), text);
      if (e.task) { const t = el("button", "tchip", e.task); t.type = "button"; t.onclick = () => openTask(e.task, ids); row.append(t); } else row.append(el("span"));
      box.append(row);
    }
    const plan = body.querySelector(".plan-box, .actions-box");
    if (plan) body.insertBefore(box, plan); else body.append(box);
    btn.textContent = "Hide evidence"; scrollDown();
  } catch (e) { toast(e.message, true); }
  btn.disabled = false;
}

// ---- Agent S's changes to the board, applied by mode -------------------------------------------------
const ACT = {
  create_task: {icon: "plus", verb: a => `New ${a.task}`, text: a => a.title + (a.owner ? ` · ${a.owner}` : "")},
  assign_task: {icon: "user", verb: a => `Assign ${a.task}`, text: a => `${titleOf(a.task) ? titleOf(a.task) + " " : ""}to ${a.owner}`},
  close_task: {icon: "check", verb: a => `Close ${a.task}`, text: a => a.title || titleOf(a.task)},
  start_task: {icon: "play", verb: a => `Start ${a.task}`, text: a => `${a.title || titleOf(a.task)} · on this laptop`},
};
const UNDO = {
  create_task: (a, res) => hub(withTeam(`tasks/${encodeURIComponent(res.task)}`), {method: "DELETE"}),
  assign_task: a => hub(withTeam(`tasks/${encodeURIComponent(a.task)}`), {method: "PATCH", body: {owner: a.prevOwner || ""}}),
  close_task: a => hub(withTeam(`tasks/${encodeURIComponent(a.task)}`), {method: "PATCH", body: {state: "open"}}),
};
function renderActions(body, actions, mode) {
  const box = el("div", "actions-box");
  const head = el("div", "actions-head");
  head.append(el("b", null, `${actions.length} change${actions.length > 1 ? "s" : ""} to the board`), `· ${MODES[mode].short}`);
  box.append(head);
  const rows = actions.map(a => {
    const row = el("div", "act"); const i = el("span", "aic"); i.innerHTML = icon(ACT[a.type].icon);
    const what = el("div", "what"); const line = el("div"); line.append(el("b", null, ACT[a.type].verb(a)), " ", ACT[a.type].text(a));
    what.append(line); if (a.why) what.append(el("small", null, a.why));
    const ctl = el("div", "ctl"); row.append(i, what, ctl); box.append(row);
    return {a, row, ctl, line};
  });
  const foot = el("div", "actions-foot"); box.append(foot);
  body.append(box); scrollDown();
  const runAll = async () => { for (const r of rows) if (!r.done && !r.skipped) await run(r); foot.replaceChildren(); };
  if (mode === "auto") { runAll(); return; }
  if (mode === "manual") {
    for (const r of rows) offer(r);
    const all = el("button", "btn small", "Approve all"); all.type = "button";
    all.onclick = () => { all.disabled = true; runAll(); };
    foot.append(all);
    return;
  }
  for (const r of rows) r.ctl.append(el("span", "state", "planned"));
  const go = el("button", "btn small primary"); go.type = "button"; go.append(ic("play"), "Run plan");
  const no = el("button", "btn small ghost", "Discard"); no.type = "button";
  go.onclick = () => { go.disabled = no.disabled = true; runAll(); };
  no.onclick = () => { for (const r of rows) skip(r); foot.replaceChildren(el("span", "state", "Plan discarded. Nothing changed.")); };
  foot.append(no, go);
}
function offer(r) {
  r.ctl.replaceChildren();
  const no = el("button", "btn small ghost", "Skip"); no.type = "button"; no.onclick = () => skip(r);
  const yes = el("button", "btn small primary", "Approve"); yes.type = "button"; yes.onclick = () => run(r);
  r.ctl.append(no, yes);
}
function skip(r) { r.skipped = true; r.row.className = "act skipped"; r.ctl.replaceChildren(el("span", "state", "skipped")); }
async function applyAction(a, repo) {
  const card = (S.board ? S.board.tasks : []).find(t => t.task === a.task);
  const path = `tasks/${encodeURIComponent(a.task)}`;
  if (a.type === "create_task") return hub(withTeam("tasks"), {method: "POST", body: {task: a.task, title: a.title, owner: a.owner || null}});
  if (a.type === "assign_task") { a.prevOwner = card ? card.owner || "" : ""; return hub(withTeam(path), {method: "PATCH", body: {owner: a.owner}}); }
  if (a.type === "close_task") return hub(withTeam(path), {method: "PATCH", body: {state: "closed"}});
  return api("/api/laptop/task", {method: "POST", body: {task: a.task, title: a.title || (card && card.title) || "", repo: repo || null}});
}
async function run(r, repo) {
  r.ctl.replaceChildren(el("span", "state", "working…"));
  try {
    r.result = await applyAction(r.a, repo);
    r.done = true; r.row.className = "act done";
    if (r.result && r.result.task && r.result.task !== r.a.task && r.a.type === "create_task") {
      r.a.task = r.result.task; r.line.firstChild.textContent = ACT[r.a.type].verb(r.a);
    }
    r.ctl.replaceChildren(el("span", "state", "✓ done"));
    if (UNDO[r.a.type]) { const u = el("button", "link-btn"); u.type = "button"; u.append("Undo"); u.onclick = () => undo(r); r.ctl.append(u); }
    loadBoard();
    if (r.a.type === "start_task") refreshLaptop();
  } catch (e) {
    const repos = ((S.laptop || {}).repos || []).filter(x => x.ok);
    if (e.status === 409 && r.a.type === "start_task" && repos.length > 1) return pickRepo(r, repos);
    r.row.className = "act failed"; r.ctl.replaceChildren(el("span", "state", e.message));
    const again = el("button", "link-btn", "Retry"); again.type = "button"; again.onclick = () => run(r, repo); r.ctl.append(again);
  }
}
function pickRepo(r, repos) {
  r.ctl.replaceChildren();
  const sel = el("select"); sel.setAttribute("aria-label", "Repo");
  for (const x of repos) { const o = el("option", null, x.name); o.value = x.path; sel.append(o); }
  const go = el("button", "btn small primary", "Start here"); go.type = "button"; go.onclick = () => run(r, sel.value);
  r.ctl.append(sel, go);
}
async function undo(r) {
  try {
    await UNDO[r.a.type](r.a, r.result);
    r.done = false; r.row.className = "act skipped"; r.ctl.replaceChildren(el("span", "state", "undone")); loadBoard();
  } catch (e) { toast(e.message, true); }
}

async function digest() {
  if (!S.team) return;
  userMsg("Today's digest");
  const slot = agentMsg();
  try {
    const d = await hub(withTeam(`digest?model=${S.model}`));
    settle(slot, shortModel(d.model));
    const box = el("div", "digest"); box.append(el("div", "answer", d.headline));
    for (const [k, label] of [["shipped", "Shipped"], ["in_progress", "In progress"], ["blocked", "Blocked"], ["at_risk", "At risk"]]) {
      if (!d[k] || !d[k].length) continue;
      const ul = el("ul");
      for (const it of d[k]) { const li = el("li", null, it.text); li.append(el("span", "cite", `${it.evidence_ids.length} cited`)); ul.append(li); }
      box.append(el("h4", k === "blocked" || k === "at_risk" ? "bad" : null, label), ul);
    }
    slot.body.append(box);
  } catch (e) { settle(slot); slot.body.append(el("div", "answer", e.message)); }
  scrollDown();
}

// ---- the composer: import, mode, model ---------------------------------------------------------------
function setMode(mode, save = true) {
  S.mode = MODES[mode] ? mode : "manual";
  const m = MODES[S.mode];
  $("modePick").className = `cbtn mode ${S.mode}`; $("modeLabel").textContent = m.label;
  $("modeIc").innerHTML = icon(m.icon); $("modeHint").textContent = m.desc;
  if (save) api("/api/prefs", {method: "POST", body: {mode: S.mode}}).catch(() => {});
}
function setModel(model, save = true) {
  S.model = MODELS[model] ? model : "auto";
  $("modelLabel").textContent = MODELS[S.model].label;
  if (save) api("/api/prefs", {method: "POST", body: {model: S.model}}).catch(() => {});
}
function fillMenu(menuId, entries, current, pick) {
  const m = $(menuId); m.replaceChildren();
  for (const [key, label, small, iconName, keyHint] of entries) {
    const b = el("button", key === current ? "on" : null); b.type = "button";
    b.setAttribute("role", "menuitemradio"); b.setAttribute("aria-checked", String(key === current));
    const words = el("span"); words.append(el("b", null, label), el("small", null, small));
    b.append(ic(key === current ? "check" : iconName), words);
    if (keyHint) b.append(el("span", "key", keyHint));
    b.onclick = () => { closeMenus(); pick(key); $("askIn").focus(); };
    m.append(b);
  }
}
function toggleMenu(btnId, menuId, fill) {
  const m = $(menuId); const open = m.hidden; closeMenus(); if (!open) return;
  fill(); m.hidden = false; $(btnId).setAttribute("aria-expanded", "true");
}
$("modePick").onclick = () => toggleMenu("modePick", "modeMenu", () => fillMenu("modeMenu",
  MODE_ORDER.map((k, i) => [k, MODES[k].label, MODES[k].desc, MODES[k].icon, i === 0 ? "Shift+Tab" : ""]), S.mode, setMode));
$("modelBtn").onclick = () => toggleMenu("modelBtn", "modelMenu", () => fillMenu("modelMenu",
  Object.keys(MODELS).map(k => [k, MODELS[k].label, MODELS[k].desc, "chip"]), S.model, setModel));
$("importBtn").onclick = () => toggleMenu("importBtn", "importMenu", () => {});

function renderChips() {
  const c = $("chips"); c.replaceChildren();
  S.files.forEach((f, i) => c.append(fileChip(f.name, f.size, () => { S.files.splice(i, 1); renderChips(); })));
  c.hidden = !S.files.length;
}
async function addFiles(list) {
  for (const f of list) {
    if (S.files.length >= MAX_FILES) { toast(`Up to ${MAX_FILES} imports per message.`, true); break; }
    if (f.size > MAX_FILE_BYTES) { toast(`${f.name} is over ${Math.round(MAX_FILE_BYTES / 1000)} KB.`, true); continue; }
    const text = await f.text();
    if (text.slice(0, 4000).includes("\u0000")) { toast(`${f.name} isn't a text file.`, true); continue; }
    S.files.push({name: f.name, text: text.slice(0, 60000), size: f.size});
  }
  renderChips(); $("askIn").focus();
}
$("importFiles").onclick = () => { closeMenus(); $("fileIn").click(); };
$("fileIn").onchange = async () => { await addFiles([...$("fileIn").files]); $("fileIn").value = ""; };
$("askForm").addEventListener("dragover", e => { if ([...e.dataTransfer.types].includes("Files")) e.preventDefault(); });
$("askForm").addEventListener("drop", e => { if (e.dataTransfer.files.length) { e.preventDefault(); addFiles([...e.dataTransfer.files]); } });
$("importIssues").onclick = () => { closeMenus(); $("issuesForm").hidden = false; $("issuesErr").textContent = ""; $("issuesIn").focus(); };
$("issuesCancel").onclick = () => { $("issuesForm").hidden = true; };
$("issuesForm").addEventListener("submit", async ev => {
  ev.preventDefault();
  const b = ev.submitter; if (b) b.disabled = true; $("issuesErr").textContent = "";
  try {
    if (S.files.length >= MAX_FILES) throw new Error(`Up to ${MAX_FILES} imports per message.`);
    const r = await api(`/api/import/github?repo=${encodeURIComponent($("issuesIn").value.trim())}`);
    S.files.push({name: r.name, text: r.text, size: r.text.length}); renderChips();
    $("issuesForm").hidden = true; $("issuesIn").value = "";
    if (!askIn.value.trim()) askIn.value = "Plan these issues as tasks and suggest an owner for each.";
    askIn.focus();
  } catch (err) { $("issuesErr").textContent = err.message; }
  if (b) b.disabled = false;
});

const askIn = $("askIn");
askIn.addEventListener("input", () => { askIn.style.height = "auto"; askIn.style.height = `${Math.min(askIn.scrollHeight, 180)}px`; });
askIn.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("askForm").requestSubmit(); }
  if (e.key === "Tab" && e.shiftKey) { e.preventDefault(); setMode(MODE_ORDER[(MODE_ORDER.indexOf(S.mode) + 1) % MODE_ORDER.length]); }
});
$("askForm").addEventListener("submit", e => { e.preventDefault(); const q = askIn.value.trim(); if (!q) return; askIn.value = ""; askIn.style.height = "auto"; ask(q); });
$("digestBtn").onclick = digest;

// ---- board -------------------------------------------------------------------------------------------------
function pose(t, members) {
  if (t.status === "blocked") return "oops";
  if ((t.progress || {}).percent >= 90) return "cheer";
  const active = new Set(members.filter(m => m.active).map(m => m.name));
  return t.members.some(m => active.has(m)) ? "idle" : "sleep";
}
function list(label, items, cls, task) {
  if (!items || !items.length) return null;
  const row = el("div", "lrow " + (cls || "")); row.append(el("span", null, label));
  const ul = el("ul");
  for (const it of items) { const li = el("li", null, it.text); const c = el("span", "cite", `${it.evidence_ids.length} cited`); li.append(c); ul.append(li); }
  row.append(ul); return row;
}
function card(t, members, i) {
  const c = el("article", "card" + (t.status === "blocked" ? " blocked" : "")); c.style.animationDelay = `${Math.min(i, 8) * 40}ms`;
  const head = el("div", "card-head"); head.append(mascot(t.members[0] || "team", pose(t, members)));
  const open = el("button", "card-open"); open.type = "button"; open.title = "Open the timeline"; open.onclick = () => openTask(t.task);
  open.append(el("div", "tid", t.task), el("h3", null, t.title || t.task));
  head.append(open, el("span", "status " + t.status, t.status === "todo" ? "to do" : t.status.replace("_", " "))); c.append(head);
  const p = t.progress;
  if (t.status === "todo") {
    c.classList.add("todo");
    c.append(el("div", "notyet", t.owner ? `Not started · ${t.owner} is on it` : "Not started · nobody assigned yet"));
    const foot = el("div", "card-foot"); foot.append(el("span", null, `planned ${ago(t.last_activity)}`)); c.append(foot);
    return c;
  }
  const meter = el("div", "meter"), track = el("div", "track"), fill = el("div", "fill");
  fill.style.width = "0%"; track.append(fill); requestAnimationFrame(() => { fill.style.width = `${p ? p.percent : 0}%`; });
  if (p && p.agent_says_percent != null) { const m = el("div", "claim"); m.style.left = `calc(${p.agent_says_percent}% - 1px)`; m.title = "what the coding agent claims"; track.append(m); }
  const legend = el("div", "legend"); const a = el("span"); a.append("Agent S ", el("b", null, p ? `${p.percent}%` : "estimating…"));
  if (p) a.append(` · ${p.confidence}`); legend.append(a);
  if (p && p.agent_says_percent != null) legend.append(el("span", null, `agent says ${p.agent_says_percent}%`));
  meter.append(track, legend); c.append(meter);
  if (p) { const lists = el("div", "lists"); for (const r of [list("Blocked", p.blockers, "blockers", t.task), list("Done", p.done, "", t.task), list("Doing", p.doing, "", t.task), list("Next", p.next, "", t.task)]) if (r) lists.append(r); if (lists.childElementCount) c.append(lists); }
  const foot = el("div", "card-foot");
  if (t.owner && !t.members.includes(t.owner)) foot.append(el("span", "tag", `owner ${t.owner}`));
  for (const m of t.members) foot.append(el("span", "tag", m));
  for (const tool of t.tools) if (TOOLS[tool]) foot.append(el("span", "tag", TOOLS[tool]));
  if (t.pr) foot.append(el("span", "tag pr", [`PR #${t.pr.number}`, t.pr.draft ? "draft" : t.pr.state, t.pr.checks ? `CI ${t.pr.checks}` : ""].filter(Boolean).join(" · ")));
  foot.append(el("span", null, `${ago(t.last_activity)} · ${t.events} events`));
  c.append(foot); return c;
}
function renderBoard() {
  const grid = $("cards"); const b = S.board;
  if (!b) { grid.replaceChildren(el("div", "skeleton"), el("div", "skeleton"), el("div", "skeleton")); return; }
  const counts = {todo: 0, in_progress: 0, blocked: 0, review: 0, done: 0};
  for (const t of b.tasks) counts[t.status] = (counts[t.status] || 0) + 1;
  const tally = $("tally"); tally.replaceChildren();
  for (const [k, v, cls] of [["tasks", b.tasks.length], ["to do", counts.todo], ["in progress", counts.in_progress], ["blocked", counts.blocked, counts.blocked ? "bad" : ""], ["in review", counts.review], ["done", counts.done]]) {
    const s = el("span", cls || null); s.append(el("b", null, String(v)), k); tally.append(s);
  }
  $("boardSub").textContent = `${b.room} · Agent S progress from every teammate's sessions`;
  grid.replaceChildren();
  if (!b.tasks.length) {
    const e = el("div", "empty"); e.style.gridColumn = "1 / -1";
    const go2 = el("button", "btn primary", "Connect a repo"); go2.type = "button"; go2.onclick = () => go("laptop");
    e.append(mascot(S.user.name, "sleep"), el("h3", null, "No task activity yet"),
      el("p", "sub", "Connect a repo on this laptop, then start a Claude Code or Codex session. Tasks show up here as you work."), go2);
    grid.append(e); return;
  }
  b.tasks.forEach((t, i) => grid.append(card(t, b.members, i)));
}

// ---- task drawer ------------------------------------------------------------------------------------------
let openedFrom = null;
const SVGNS = "http://www.w3.org/2000/svg";
function svg(tag, attrs) { const n = document.createElementNS(SVGNS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); return n; }
function sparkline(history) {
  const box = el("div", "spark");
  if (!history.length) { box.append(el("div", "label", "No Agent S estimate yet")); return box; }
  const W = 500, H = 90, pad = 8, n = history.length;
  const x = i => n === 1 ? W / 2 : pad + i * (W - 2 * pad) / (n - 1);
  const y = p => H - pad - (Math.max(0, Math.min(100, p)) / 100) * (H - 2 * pad);
  const s = svg("svg", {viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Agent S progress over time"});
  for (const g of [0, 50, 100]) s.append(svg("line", {x1: 0, x2: W, y1: y(g), y2: y(g), stroke: "currentColor", "stroke-opacity": .1}));
  s.append(svg("polyline", {points: history.map((h, i) => `${x(i)},${y(h.percent)}`).join(" "), fill: "none", stroke: "var(--brick)", "stroke-width": 3, "stroke-linejoin": "round", "stroke-linecap": "round"}));
  history.forEach((h, i) => s.append(svg("circle", {cx: x(i), cy: y(h.percent), r: 3.5, fill: "var(--brick)"})));
  box.append(s, el("div", "label", `${n} estimate${n > 1 ? "s" : ""} · now ${history[n - 1].percent}%`)); return box;
}
async function openTask(task, highlight) {
  openedFrom = document.activeElement;
  try {
    const d = await hub(withTeam(`tasks/${encodeURIComponent(task)}`));
    $("dId").textContent = d.task; $("dTitle").textContent = d.title || d.task;
    const body = $("dBody"); body.replaceChildren(sparkline(d.history || []));
    const p = d.progress || {}; const lists = el("div", "lists");
    for (const r of [list("Blocked", p.blockers, "blockers"), list("Done", p.done), list("Doing", p.doing), list("Next", p.next)]) if (r) lists.append(r);
    if (lists.childElementCount) body.append(lists);
    body.append(el("div", "label", "Timeline, newest first"));
    if (!d.timeline.length) body.append(el("p", "sub", d.owner ? `Planned for ${d.owner}. When a session starts on ${d.task}, it shows up here.`
      : `Planned. When someone starts a session on ${d.task}, it shows up here.`));
    const ol = el("ol", "timeline"); const hit = new Set(highlight || []);
    for (const e of d.timeline) {
      const li = el("li", hit.has(e.id) ? "hit" : null); const t = el("div");
      t.append(el("b", null, `${e.member}${TOOLS[e.tool] ? " · " + TOOLS[e.tool] : ""}  `), e.line);
      li.append(el("time", null, clock(e.ts)), t); ol.append(li);
    }
    body.append(ol);
    $("scrim").hidden = false; $("drawer").hidden = false; $("dClose").focus();
    const first = ol.querySelector(".hit"); if (first) first.scrollIntoView({block: "center"});
  } catch (e) { toast(e.message, true); }
}
function closeTask() { $("drawer").hidden = true; $("scrim").hidden = true; if (openedFrom) openedFrom.focus(); }
$("dClose").onclick = closeTask; $("scrim").onclick = closeTask;

// ---- team -------------------------------------------------------------------------------------------------
async function loadTeam() {
  const t = team(); const lead = t && t.role === "lead";
  $("inviteCard").hidden = !lead;
  $("teamSub").textContent = t ? `${t.name} · ${lead ? "you lead this team" : "member"}` : "";
  const grid = $("people");
  try {
    const r = await hub(withTeam("team"));
    grid.replaceChildren();
    r.members.forEach((m, i) => {
      const c = el("article", "person" + (m.removed ? " removed" : "")); c.style.animationDelay = `${Math.min(i, 8) * 40}ms`;
      c.append(mascot(m.name, m.removed || !m.active ? "sleep" : "idle"));
      const b = el("div"); b.style.minWidth = "0";
      const seen = m.removed ? "removed by the lead" : m.active ? "active now" : m.last_activity ? `last seen ${ago(m.last_activity)}` : "no sessions yet";
      b.append(el("h3", null, m.name), el("div", "meta", [seen, m.member_role === "lead" ? "lead" : "", m.email || ""].filter(Boolean).join(" · ")));
      const ul = el("ul");
      for (const tool of m.tools) ul.append(el("li", "tag", TOOLS[tool] || tool));
      for (const tk of m.tasks.slice(0, 4)) { const li = el("li"); const x = el("button", "tchip", tk.task); x.type = "button"; x.onclick = () => openTask(tk.task); li.append(x); ul.append(li); }
      b.append(ul);
      if (lead && m.user_id !== S.user.id) b.append(manage(m));
      c.append(b); grid.append(c);
    });
    if (!r.members.length) grid.append(el("div", "empty", "Nobody here yet."));
  } catch (e) { toast(e.message, true); }
}
function manage(m) {
  const box = el("div", "actions");
  const base = `teams/${S.team}/members/${m.user_id}`;
  const act = async (method, path, done) => { try { await hub(path, {method, body: method === "POST" ? {} : undefined}); toast(done); loadTeam(); } catch (e) { toast(e.message, true); } };
  if (m.removed) { const b = el("button", "btn small", "Restore"); b.type = "button"; b.onclick = () => act("POST", `${base}/restore`, `${m.name} is back.`); box.append(b); return box; }
  const b = el("button", "btn small ghost", "Remove"); b.type = "button";
  b.onclick = () => {
    box.replaceChildren(el("span", "sub", "Their updates stop; history stays."));
    const yes = el("button", "btn small danger", "Remove"); yes.type = "button"; yes.onclick = () => act("DELETE", base, `${m.name} was removed.`);
    const no = el("button", "btn small ghost", "Cancel"); no.type = "button"; no.onclick = () => box.replaceChildren(b);
    box.append(yes, no); yes.focus();
  };
  box.append(b); return box;
}
$("inviteBtn").onclick = async () => {
  const b = $("inviteBtn"); b.disabled = true;
  try {
    const r = await hub(`teams/${S.team}/invites`, {method: "POST", body: {role: "member"}});
    $("inviteOut").value = r.url; $("inviteOut").select();
    try { await navigator.clipboard.writeText(r.url); toast("Invite link copied. It works for 7 days."); } catch (e) { toast("Invite link ready. Copy it from the box."); }
  } catch (e) { toast(e.message, true); }
  b.disabled = false;
};

// ---- this laptop --------------------------------------------------------------------------------------------
function renderLaptop() {
  const L = S.laptop || {}; const grid = $("laptopGrid"); grid.replaceChildren();
  const left = el("div", "stack"), right = el("div", "stack");

  const rep = el("section", "panel"); rep.append(el("h3", null, "Reporting"));
  if (!L.team) {
    rep.append(el("p", "sub", `Connect this laptop and its coding sessions start reporting to ${team() ? team().name : "your team"}.`));
    const b = el("button", "btn primary", `Connect to ${team() ? team().name : "team"}`); b.type = "button";
    b.onclick = async () => { b.disabled = true; try { S.laptop = await api("/api/laptop/team", {method: "POST", body: {team: S.team}}); toast("This laptop is connected."); renderLaptopChip(); renderLaptop(); } catch (e) { toast(e.message, true); b.disabled = false; } };
    rep.append(b);
  } else {
    const kv = el("dl", "kv");
    kv.append(el("dt", null, "Team"), el("dd", null, L.team.name), el("dt", null, "As"), el("dd", null, L.name || ""),
      el("dt", null, "Waiting"), el("dd", null, `${L.pending} event${L.pending === 1 ? "" : "s"} to send`));
    rep.append(kv);
    if (L.team.id !== S.team && team()) {
      const sw = el("button", "btn", `Report to ${team().name} instead`); sw.type = "button";
      sw.onclick = async () => { try { S.laptop = await api("/api/laptop/team", {method: "POST", body: {team: S.team}}); renderLaptopChip(); renderLaptop(); toast(`This laptop reports to ${team().name} now.`); } catch (e) { toast(e.message, true); } };
      rep.append(sw);
    }
    const s = el("div", "switch"); const words = el("div"); words.append(el("b", null, L.paused ? "Sharing is paused" : "Sharing is on"), el("small", null, L.paused ? "Hooks record nothing until you turn it back on." : "Summaries and facts go to your team as you work."));
    const tg = el("button", "toggle"); tg.type = "button"; tg.setAttribute("role", "switch"); tg.setAttribute("aria-checked", String(!L.paused)); tg.setAttribute("aria-label", "Sharing");
    tg.onclick = async () => { S.laptop = await api("/api/laptop/pause", {method: "POST", body: {paused: !L.paused}}); renderLaptopChip(); renderLaptop(); };
    s.append(words, tg); rep.append(s);
    if (L.pending) { const send = el("button", "btn ghost", "Send now"); send.type = "button"; send.onclick = async () => { send.disabled = true; const r = await api("/api/laptop/send", {method: "POST"}).catch(e => ({error: e.message})); toast(r.error ? `Not sent: ${r.error}` : `Sent ${r.sent} event${r.sent === 1 ? "" : "s"}.`, !!r.error); refreshLaptop(true); }; rep.append(send); }
  }
  left.append(rep);

  const repos = el("section", "panel"); repos.append(el("h3", null, "Repos"), el("p", "sub", "Each connected repo reports its Claude Code and Codex sessions. Hooks go in personal files, kept out of git."));
  const ul = el("ul", "repos");
  for (const r of L.repos || []) {
    const li = el("li", "repo"); const f = el("span", "folder"); f.append(ic("folder"));
    const checks = el("div", "checks");
    checks.append(el("span", "ck " + (r.claude_code ? "ok" : "no"), r.claude_code ? "Claude Code ✓" : "Claude Code ✗"));
    if (r.codex !== null) checks.append(el("span", "ck " + (r.codex ? "ok" : "no"), r.codex ? "Codex ✓" : "Codex ✗"));
    if (r.task) checks.append(el("span", "ck", r.task));
    const name = el("b", null, r.name); name.title = r.path;
    li.append(f, name, checks); ul.append(li);
  }
  if (!(L.repos || []).length) ul.append(el("li", "sub", "No repos connected yet."));
  const add = el("button", "btn primary", "Connect a repo"); add.type = "button";
  const log = el("pre", "log"); log.hidden = true;
  add.onclick = async () => {
    add.disabled = true; add.textContent = "Pick the repo folder…";
    try {
      const r = await api("/api/laptop/repos", {method: "POST", body: {}});
      if (!r.cancelled) { log.textContent = r.log; log.hidden = false; toast(r.ok ? `Connected ${r.repo.name}. Restart its coding sessions.` : "That folder isn't a git repo.", !r.ok); await refreshLaptop(false); }
    } catch (e) { toast(e.message, true); }
    add.disabled = false; add.textContent = "Connect a repo";
    if (S.view === "laptop") { const keep = log.hidden ? null : log.textContent; renderLaptop(); if (keep) { const l2 = $("laptopGrid").querySelector(".log"); l2.textContent = keep; l2.hidden = false; } }
  };
  repos.append(ul, add, log); left.append(repos);

  const tools = el("section", "panel"); tools.append(el("h3", null, "Coding tools on this laptop"));
  const T = L.tools || {}; const tl = el("ul", "repos");
  for (const [k, label, hint] of [["claude_code", "Claude Code", "the claude CLI wasn't found on PATH"], ["codex", "Codex", "the codex CLI wasn't found on PATH"]]) {
    const li = el("li", "repo"); const f = el("span", "folder"); f.append(ic(T[k] ? "check" : "x"));
    li.append(f, el("b", null, label), el("span", "sub", T[k] ? "found" : hint)); tl.append(li);
  }
  tools.append(tl); right.append(tools);

  const never = el("section", "panel"); never.append(el("h3", null, "Never leaves this laptop"));
  const nv = el("div", "never");
  for (const line of ["Your prompts and the agent's replies", "Tool output, file contents and diffs", "Keystrokes, screenshots, time tracking"]) { const p = el("div"); p.append("✕  ", el("b", null, line)); nv.append(p); }
  nv.append(el("p", "sub", "What goes: a one-line summary per turn, written on this laptop, plus facts such as files changed and tests passed or failed."));
  never.append(nv); right.append(never);
  grid.append(left, right);
}

start();
