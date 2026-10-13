"use strict";
// Super Agents UI. Text that comes from teammates, the model or files is untrusted: it goes in with textContent, or as
// Markdown through DOMPurify (answers, skills, .md files). innerHTML is otherwise used only for this file's own icons
// and marks, and for highlight.js output (which escapes what it highlights).

const $ = id => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const HASH = new URLSearchParams(location.hash.slice(1));  // k: the per-launch key from the app window; view/ask: screenshots
const KEY = (() => {
  const k = HASH.get("k") || sessionStorage.getItem("sa-key");
  if (k) sessionStorage.setItem("sa-key", k);
  history.replaceState(null, "", "/");
  return k || "";
})();
const S = {boot: null, user: null, teams: [], team: null, board: null, laptop: null, view: "chat",
  mode: "manual", model: "auto", files: [], agents: [], colors: [], agent: "agent-s", chat: null, turn: null,
  running: false, chats: [], connectors: []};
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep = ms => new Promise(r => setTimeout(r, ms));

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
  user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/>',
  bot: '<rect x="4.5" y="7.5" width="15" height="11.5" rx="3.5"/><path d="M12 7.5v-3"/><circle cx="12" cy="3.7" r="1"/><path d="M9.3 12.7h.01M14.7 12.7h.01" stroke-width="2.6"/><path d="M9.6 16h4.8"/>',
  term: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="m7.5 9.5 3 2.5-3 2.5M12.5 15h4"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.4 3.6 5.3 3.6 8.5s-1.2 6.1-3.6 8.5c-2.4-2.4-3.6-5.3-3.6-8.5S9.6 5.9 12 3.5Z"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.3-4.3"/>',
  edit: '<path d="M4.5 19.5h4l10-10a2.8 2.8 0 0 0-4-4l-10 10Z"/><path d="m13.5 6.5 4 4"/>',
  book: '<path d="M5 4.5h9.5a3 3 0 0 1 3 3v12h-9.5a3 3 0 0 1-3-3Z"/><path d="M5 16.5a3 3 0 0 1 3-3h9.5"/>',
  plug: '<path d="M9 3.5v4M15 3.5v4"/><path d="M6.5 7.5h11V11a5.5 5.5 0 0 1-11 0Z"/><path d="M12 16.5v4"/>',
  stop: '<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor"/>',
  reload: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4h-4"/>',
  external: '<path d="M14 4.5h5.5V10"/><path d="M19.5 4.5 11 13"/><path d="M17.5 14v4a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2h4"/>',
  caret: '<path d="m10 7 5 5-5 5"/>',
  copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5v-2a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2"/>',
  gauge: '<path d="M4.2 16.5a8 8 0 1 1 15.6 0"/><path d="m12 16.5 3.6-4.6"/><circle cx="12" cy="16.5" r="1.2"/>',
  sidebar: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M9.5 4.5v15"/>',
  back: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
  branch: '<circle cx="7" cy="5.5" r="2.2"/><circle cx="7" cy="18.5" r="2.2"/><circle cx="17" cy="8" r="2.2"/><path d="M7 7.7v8.6M17 10.2c0 4.3-6.5 3.2-9.3 6.4"/>',
  prefs: '<path d="M4 7.5h9M18 7.5h2M4 16.5h3M12 16.5h8"/><circle cx="15.5" cy="7.5" r="2.3"/><circle cx="9.5" cy="16.5" r="2.3"/>',
  expand: '<path d="M14.5 4.5h5v5M9.5 19.5h-5v-5M19.5 4.5 13.5 10.5M4.5 19.5l6-6"/>',
  shrink: '<path d="M18.5 10.5h-5v-5M5.5 13.5h5v5M13.5 10.5l6-6M10.5 13.5l-6 6"/>',
};
// Like Claude Code's modes: Shift+Tab cycles them.
const MODES = {
  manual: {label: "Manual", icon: "hand", desc: "Asks before each change: tasks, files, connector actions."},
  auto: {label: "Auto", icon: "bolt", desc: "Makes routine changes itself and tells you. Shell commands still ask first."},
  plan: {label: "Plan", icon: "list", desc: "Works out a plan first. Nothing changes until you run it."},
};
const MODE_ORDER = ["manual", "auto", "plan"];
const MODELS = {
  auto: {label: "Auto", desc: "Nemotron Super for chats, Ultra for the digest"},
  lightning: {label: "Nemotron Lightning", desc: "Fastest replies"},
  super: {label: "Nemotron Super", desc: "Balanced · 120B"},
  ultra: {label: "Nemotron Ultra", desc: "Deepest reasoning · 550B"},
};
const TOOL_GROUPS = {
  team: {label: "Team board", desc: "Read the board and the team's history; create, assign, close and start tasks."},
  files: {label: "Files and git", desc: "Read, search and write files in the repos connected on This laptop; branch, commit, push and open pull requests."},
  terminal: {label: "Terminal", desc: "Run shell commands on this laptop. Always asks first."},
  browser: {label: "Browser", desc: "Read web pages and show pages in the browser panel."},
  memory: {label: "Memory", desc: "Remember notes, and search earlier chats and your coding sessions in every project on this laptop."},
  desktop: {label: "Desktop", desc: "Use Windows apps through their controls, without your mouse or keyboard. Each app asks first; never Settings, security or password apps. Off until you turn it on."},
};
const MAX_FILES = 5, MAX_FILE_BYTES = 200_000;
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg>`;
function paintIcons(root = document) { root.querySelectorAll(".ic[data-ic]").forEach(n => { if (!n.firstElementChild) n.innerHTML = icon(n.dataset.ic); }); }
function ic(name) { const s = el("span", "ic"); s.innerHTML = icon(name); return s; }

const HOOD = "M50 95C30 95 14 93 11 86C8.5 80 9 68 9.5 56C11 31 27 14 48 12.5C56 12 63 9.5 70 3.5C71.2 9.5 69.8 14.5 66.5 17.8C81 25 90 39 90.5 56C91 68 91.5 80 89 86C86 93 70 95 50 95Z";
function agent(cls = "", hood = "") {
  const t = document.createElement("template");
  t.innerHTML = `<svg class="agent ${cls}" viewBox="0 0 100 100" aria-hidden="true"${/^#[0-9a-fA-F]{6}$/.test(hood) ? ` style="--hood:${hood}"` : ""}><path class="hood" d="${HOOD}"/>`
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

// Markdown from the model, skills and files: sanitized, code highlighted, links open in the browser panel.
if (window.hljs) hljs.configure({ignoreUnescapedHTML: true});
function renderMd(box, text) {
  box.innerHTML = DOMPurify.sanitize(marked.parse(text || "", {gfm: true, breaks: false}), {USE_PROFILES: {html: true}});
  box.querySelectorAll("pre code").forEach(c => { try { hljs.highlightElement(c); } catch (e) { /* stays plain */ } });
}
document.addEventListener("click", e => {
  const a = e.target.closest(".md a[href]");
  if (!a) return;
  e.preventDefault();
  if (/^https?:/i.test(a.getAttribute("href"))) openBrowser(a.getAttribute("href"));
});

// ---- theme ----------------------------------------------------------------------------------------
function setTheme(theme, save = true) {
  document.documentElement.dataset.theme = theme;
  $("themeLabel").textContent = theme === "dark" ? "Light theme" : "Dark theme";
  const t = $("themeBtn").querySelector(".ic"); t.dataset.ic = theme === "dark" ? "sunny" : "moon"; t.innerHTML = icon(t.dataset.ic);
  for (const b of document.querySelectorAll(".theme-seg button")) b.setAttribute("aria-pressed", String(b.textContent.toLowerCase() === theme));
  for (const x of TERMS.list) x.term.options.theme = termTheme();
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
  const prefs = boot.prefs || {};
  setTheme(prefs.theme || "dark", false);
  setMode(prefs.mode || "manual", false);
  setModel(prefs.model || "auto", false);
  S.agent = prefs.agent || "agent-s";
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
const VIEWS = ["chat", "board", "team", "agents", "laptop", "settings"];
function showShell() {
  show("shell");
  $("railMark").replaceChildren(agent());
  $("meName").textContent = S.user.name;
  $("meBtn").dataset.tip = S.user.name;
  setRail($("shell").classList.contains("rail-min"), false);
  $("meRole").textContent = team() ? `${team().role === "lead" ? "Lead" : "Member"} · ${team().name}` : "";
  const av = $("meAvatar"); av.replaceChildren();
  if (S.user.avatar) { const i = el("img"); i.src = S.user.avatar; i.alt = ""; av.append(i); } else av.textContent = (S.user.name || "?").slice(0, 1).toUpperCase();
  $("versionLine").textContent = `Super Agents ${S.boot.version}`;
  $("teamName").textContent = team() ? team().name : "Pick a team";
  renderLaptopChip();
  if (!$("thread").childElementCount) renderHello();
  go(HASH.get("view") || S.view);
  HASH.delete("view");
  loadAgents().then(() => { if ($("thread").querySelector(".hello")) renderHello(); loadChats(); });
  api("/api/connectors").then(r => { S.connectors = r.items; }).catch(() => {});
  loadBoard().then(() => { if (HASH.get("ask")) { ask(HASH.get("ask")); HASH.delete("ask"); } });
  loadUsageChip();
  if (HASH.get("pane")) { openPane(HASH.get("pane")); HASH.delete("pane"); }
  clearInterval(pollTimer);
  let ticks = 0;
  checkInbox();
  pollTimer = setInterval(() => { if (!document.hidden) { loadBoard(); refreshLaptop(); checkInbox(); if (++ticks % 3 === 0) loadUsageChip(); } }, 20000);
}
function go(view) {
  S.view = VIEWS.includes(view) ? view : "chat";
  setSideWide(false);  // a view you pick should show, not sit behind a full-width panel
  for (const b of document.querySelectorAll("#nav button")) b.classList.toggle("on", b.dataset.view === S.view);
  for (const v of VIEWS) $(`view-${v}`).hidden = v !== S.view;
  if (S.view === "board") renderBoard();
  if (S.view === "team") showTeamTab(teamTab);
  if (S.view === "agents") showAgentTab(agentTab);
  if (S.view === "laptop") refreshLaptop(true);
  if (S.view === "settings") renderSettings();
  if (S.view === "chat") setTimeout(() => $("askIn").focus(), 50);
}
for (const b of document.querySelectorAll("#nav button")) b.onclick = () => go(b.dataset.view);
$("laptopChip").onclick = () => go("laptop");
$("usageChip").onclick = () => { teamTab = "usage"; go("team"); };
$("newChat").onclick = () => newChat();
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { closeMenus(); if (!$("drawer").hidden) closeDrawer(); }
  if (e.ctrlKey && e.key.toLowerCase() === "n" && !$("shell").hidden) { e.preventDefault(); newChat(); }
  if (e.ctrlKey && e.key === "`" && !$("shell").hidden) { e.preventDefault(); togglePane("terminal"); }
  // Ctrl+B is the shell's own key inside a terminal, so it's left alone there
  if (e.ctrlKey && e.key.toLowerCase() === "b" && !$("shell").hidden && !e.target.closest(".terms")) { e.preventDefault(); setRail(!$("shell").classList.contains("rail-min")); }
  if (e.ctrlKey && e.key === "," && !$("shell").hidden) { e.preventDefault(); closeMenus(); go("settings"); }
});

// The sidebar folds to icons (its button or Ctrl+B); the names become tooltips. Remembered on this laptop.
function setRail(min, save = true) {
  $("shell").classList.toggle("rail-min", min);
  const t = $("railToggle"), words = min ? "Expand the sidebar" : "Collapse the sidebar";
  t.setAttribute("aria-label", words); t.title = `${words} (Ctrl+B)`; t.setAttribute("aria-expanded", String(!min));
  for (const b of document.querySelectorAll(".rail [data-tip]")) b.title = min ? b.dataset.tip : "";
  if (save) try { localStorage.setItem("sa-rail", min ? "min" : "full"); } catch (e) { /* stays for this run */ }
}
$("railToggle").onclick = () => setRail(!$("shell").classList.contains("rail-min"));
try { setRail(localStorage.getItem("sa-rail") === "min", false); } catch (e) { setRail(false, false); }

function closeMenus() {
  for (const id of ["meMenu", "teamMenu", "importMenu", "modeMenu", "modelMenu", "agentMenu"]) $(id).hidden = true;
  document.querySelectorAll('.cwrap > [aria-expanded="true"]').forEach(b => b.setAttribute("aria-expanded", "false"));
}
document.addEventListener("click", e => { if (!e.target.closest(".menu, #meBtn, #teamBtn, .cwrap")) closeMenus(); });
$("meBtn").onclick = () => { const m = $("meMenu"); const open = m.hidden; closeMenus(); m.hidden = !open; };
$("settingsBtn").onclick = () => { closeMenus(); go("settings"); };
$("themeBtn").onclick = () => { setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"); closeMenus(); };
$("signOutBtn").onclick = async () => {
  closeMenus(); clearInterval(pollTimer);
  await api("/api/auth/signout", {method: "POST"}).catch(() => {});
  S.user = null; S.board = null; S.chat = null; $("thread").replaceChildren();
  await reboot();
};
$("teamBtn").onclick = () => {
  const m = $("teamMenu"); const open = m.hidden; closeMenus(); if (!open) return;
  m.replaceChildren();
  for (const t of S.teams) {
    const b = el("button", t.id === S.team ? "on" : null); b.type = "button";
    b.append(ic(t.id === S.team ? "check" : "team"), el("span", null, t.name), el("small", null, t.role === "lead" ? " · lead" : ""));
    b.onclick = async () => { closeMenus(); if (t.id === S.team) return; S.team = t.id; S.board = null; await api("/api/team", {method: "POST", body: {team: t.id}}); S.chat = null; $("thread").replaceChildren(); showShell(); };
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
    li.title = `${p.name}: ${p.active ? "active in the last 5 minutes" : `last seen ${ago(p.last_activity)}`}`; ul.append(li);
  }
  if (!people.length) ul.append(el("li", "none", "Nobody has reported yet."));
}

// ---- agents: the picker --------------------------------------------------------------------------------
const currentAgent = () => S.agents.find(a => a.id === S.agent) || S.agents[0] || {id: "agent-s", name: "Agent S", color: "#C2554C", mode: "manual", model: "auto"};
async function loadAgents() {
  try { const r = await api("/api/agents"); S.agents = r.agents; S.colors = r.colors; } catch (e) { /* keep what we have */ }
  if (!S.agents.some(a => a.id === S.agent)) S.agent = "agent-s";
  renderAgentPick();
}
function renderAgentPick() {
  const a = currentAgent();
  $("agentLabel").textContent = a.name;
  $("agentMini").replaceChildren(agent("", a.color));
  $("askIn").placeholder = a.id === "agent-s" ? "Ask about your team's work, or ask Agent S to plan it…" : `Message ${a.name}…`;
  $("askIn").setAttribute("aria-label", `Message ${a.name}`);
}
function setAgent(id, save = true, defaults = true) {
  S.agent = id;
  const a = currentAgent();
  if (defaults) { setMode(a.mode || "manual", false); setModel(a.model || "auto", false); }
  renderAgentPick();
  if (save) api("/api/prefs", {method: "POST", body: {agent: a.id, mode: S.mode, model: S.model}}).catch(() => {});
}
const agentLine = a => (a.instructions || "").trim().split("\n")[0].slice(0, 80) || (a.builtin ? "Built in. Plans the team's work and answers with evidence" : "No instructions yet");
$("agentPick").onclick = () => toggleMenu("agentPick", "agentMenu", () => {
  const m = $("agentMenu"); m.replaceChildren();
  for (const a of S.agents) {
    const b = el("button", a.id === S.agent ? "on" : null); b.type = "button";
    b.setAttribute("role", "menuitemradio"); b.setAttribute("aria-checked", String(a.id === S.agent));
    const words = el("span"); words.append(el("b", null, a.name), el("small", null, agentLine(a)));
    b.append(agent("", a.color), words);
    b.onclick = () => { closeMenus(); setAgent(a.id); $("askIn").focus(); };
    m.append(b);
  }
  m.append(el("hr"));
  const manage = el("button"); manage.type = "button"; manage.append(ic("bot"), el("span", null, "Manage agents"));
  manage.onclick = () => { closeMenus(); agentTab = "agents"; go("agents"); };
  m.append(manage);
});

// ---- chats ------------------------------------------------------------------------------------------------
async function loadChats() {
  try { S.chats = (await api("/api/chats")).chats; } catch (e) { return; }
  renderChats();
}
function renderChats() {
  const ul = $("chatList"); ul.replaceChildren();
  for (const c of S.chats.slice(0, 40)) {
    const li = el("li"); const b = el("button", "c" + (c.id === S.chat ? " on" : "")); b.type = "button";
    const a = S.agents.find(x => x.id === c.agent); const dot = el("i"); if (a) dot.style.setProperty("--hood", a.color);
    b.append(dot, el("span", null, c.title || "Untitled")); b.title = `${c.title || "Untitled"} · ${ago(c.updated)}`;
    b.onclick = () => openChat(c.id);
    const x = el("button", "del"); x.type = "button"; x.setAttribute("aria-label", `Delete the chat ${c.title || ""}`); x.append(ic("x"));
    x.onclick = async ev => {  // two clicks: the first arms it
      ev.stopPropagation();
      if (!x.classList.contains("armed")) { x.classList.add("armed"); x.title = "Click again to delete"; x.style.color = "var(--bad)"; x.style.opacity = "1"; setTimeout(() => { x.classList.remove("armed"); x.removeAttribute("style"); }, 2600); return; }
      await api(`/api/chats/${c.id}`, {method: "DELETE"}).catch(() => {});
      if (S.chat === c.id) newChat();
      loadChats();
    };
    li.append(b, x); ul.append(li);
  }
  if (!S.chats.length) ul.append(el("li", "none", "Your chats show up here."));
}
function newChat() {
  if (S.running) return toast("Wait for the answer, or stop it first.", true);
  S.chat = null; $("thread").replaceChildren(); renderHello(); renderChats(); go("chat");
}
async function openChat(id) {
  if (S.running) return toast("Wait for the answer, or stop it first.", true);
  try {
    const c = await api(`/api/chats/${id}`);
    S.chat = c.id; $("thread").replaceChildren();
    if (c.agent && S.agents.some(a => a.id === c.agent)) setAgent(c.agent, false, false);
    for (const v of c.view || []) {
      userMsg(v.user, (v.files || []).map(name => ({name})));
      const st = turnState(agentMsg(S.agents.find(a => a.id === v.agent) || currentAgent()), null, v.mode);
      for (const e of v.events || []) handleEvent(st, e, true);
      finishAnswer(st, v.answer, (MODES[v.mode] ? MODES[v.mode].label : "") + spentLine(v.usage));
    }
    renderChats(); go("chat"); scrollDown(true);
  } catch (e) { toast(e.message, true); }
}

// ---- chat ------------------------------------------------------------------------------------------------
function greeting() { const h = new Date().getHours(); return h < 5 ? "Up late" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; }
function renderHello() {
  const t = $("thread"); t.replaceChildren();
  const ag = currentAgent();
  const box = el("div", "hello"); const a = agent("", ag.color);
  const first = (S.user && S.user.name || "").split(" ")[0];
  box.append(a, el("h1", null, `${greeting()}, ${first}.`),
    el("p", null, ag.id === "agent-s" ? "Ask Agent S about your team's work, or have it plan, read your repos, run commands and browse. Answers about the team point to the session events they come from."
      : `${ag.name} is ready. ${agentLine(ag).replace(/[.!]$/, "")}.`));
  const ideas = [["flag", "What's blocked right now?", "Blockers, with the sessions that show them"],
    ["gauge", "Which tasks used the most AI this week?", "Tokens by task, tool and person, from every laptop"],
    ["list", "Plan our next tasks with owners and deadlines", "Proposes changes to the board; you approve them"],
    ["sun", "Write today's digest", "Shipped, in progress, blocked, at risk"]];
  const grid = el("div", "suggest");
  for (const [i, text, small] of ideas) {
    const b = el("button"); b.type = "button";
    const words = el("span", null, text); words.append(el("small", null, small));
    b.append(ic(i), words);
    b.onclick = () => (i === "sun" ? digest() : ask(text));
    grid.append(b);
  }
  box.append(grid, el("p", "tip", "Tip: + imports a spec or GitHub issues. Shift+Tab switches mode. Ctrl+` opens a terminal."));
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
  m.append(col); t.append(m); scrollDown(true);
}
function agentMsg(a = currentAgent()) {
  const m = el("div", "msg agent"); const body = el("div", "body");
  const who = el("div", "who"); who.append(a.name);
  // Like Claude Code: the steps (tools, commands, what the agent said along the way) fold into one line you can open;
  // what waits for you (an approval, a planned change) stays in view below it.
  const box = el("div", "steps-box collapsed"), head = el("button", "steps-head"), steps = el("div", "steps"), needs = el("div", "needs");
  head.type = "button"; head.setAttribute("aria-expanded", "false"); box.hidden = true;
  head.onclick = () => head.setAttribute("aria-expanded", String(!box.classList.toggle("collapsed")));
  box.append(head, steps);
  const line = el("div", "thinking-line", S.mode === "plan" ? "Planning…" : "Thinking…");
  body.append(who, box, needs, line); m.append(agent("thinking", a.color), body); $("thread").append(m); scrollDown();
  return {m, body, who, line, steps, box, head, needs, agent: a};
}
// The folded line says what the steps did, the way Claude Code does: "Read 3 files, ran a command, took 4 browser steps".
const STEP_SAID = [[/^read_file$/, "read a file", "read # files"], [/^search_files$/, "searched the code", "searched the code # times"],
  [/^list_files$/, "listed a folder", "listed # folders"], [/^write_file$/, "edited a file", "edited # files"],
  [/^run_command$/, "ran a command", "ran # commands"], [/^(git_|github_pr$|open_pr$)/, "used git", "took # git steps"],
  [/^(browser_|fetch_url$|dev_server$)/, "used the browser", "took # browser steps"], [/^desktop_/, "used an app", "took # desktop steps"],
  [/^(remember|forget|recall)$/, "used memory", "took # memory steps"], [/^(share_|take_share$|team_files$)/, "used team files", "took # sharing steps"],
  [/^mcp__/, "used a connector", "made # connector calls"], [/^(load_skill|read_skill_file)$/, "used a skill", "took # skill steps"],
  [/^(create_task|assign_task|close_task|set_deadline|start_task)$/, "changed the board", "made # board changes"],
  [/./, "looked up the team", "made # team lookups"]];
function updateHead(st) {
  const cards = Object.values(st.cards).filter(c => c.box.parentElement === st.steps);  // not the ones waiting for you
  st.slot.box.hidden = !cards.length && !st.steps.querySelector(".narr");
  if (st.slot.box.hidden) return;
  const counts = new Map(); let failed = 0, skipped = 0, now = null;
  for (const c of cards) {
    if (["asking", "planned", "discarded", "declined"].includes(c.status)) { skipped++; continue; }  // never ran: not "ran a command"
    const k = STEP_SAID.find(([re]) => re.test(c.e.name));
    counts.set(k, (counts.get(k) || 0) + 1);
    if (c.status === "failed") failed++;
    if (c.status === "running") now = c;
  }
  const said = [...counts].map(([[, one, many], n]) => (n === 1 ? one : many.replace("#", n))).join(", ") || (skipped ? "" : "Notes along the way");
  const head = st.slot.head;
  head.replaceChildren(ic("caret"));
  if (said) head.append(el("span", "sh-said", said[0].toUpperCase() + said.slice(1)));
  if (skipped) head.append(el("span", "sh-skip", `${skipped} step${skipped === 1 ? "" : "s"} not run`));
  if (failed) head.append(el("span", "sh-bad", `${failed} failed`));
  if (now) head.append(el("span", "sh-now", `${toolUi(now.e)[1]} ${now.target ? now.target.textContent : ""}`.trim()));
}
function scrollDown(force) {
  const t = $("thread");
  if (!force && t.scrollHeight - t.scrollTop - t.clientHeight > 220) return;  // they scrolled up to read: leave them there
  requestAnimationFrame(() => t.scrollTo({top: t.scrollHeight, behavior: REDUCED ? "auto" : "smooth"}));
}
function settle(slot, meta) { slot.m.querySelector(".agent").classList.remove("thinking"); slot.line.remove(); if (meta) slot.who.append(el("small", null, meta)); }
const spentLine = u => (u && u.calls ? ` · ${fmtTok((u.in || 0) + (u.out || 0))} tokens` : "");
const shortModel = m => /ultra/i.test(m || "") ? "Nemotron Ultra" : /super/i.test(m || "") ? "Nemotron Super"
  : /lightning/i.test(m || "") ? "Nemotron Lightning" : (m || "").replace(/^ollama:/, "local ");
function setRunning(on) {
  S.running = on;
  const b = $("askBtn"); b.classList.toggle("stop", on); b.setAttribute("aria-label", on ? "Stop" : "Send");
  b.querySelector(".ic").innerHTML = icon(on ? "stop" : "up");
}

// One turn of the agent loop on this laptop: start it, then follow its events (thinking, tool cards, the answer).
async function ask(q) {
  if (!S.team || !q || S.running) return;
  const files = S.files.splice(0); renderChips();
  userMsg(q, files);
  const a = currentAgent();
  const slot = agentMsg(a);
  setRunning(true);
  try {
    const r = await api("/api/turns", {method: "POST", body: {chat: S.chat, agent: a.id, message: q, mode: S.mode, model: S.model,
      team: S.team, attachments: files.map(f => ({name: f.name, text: f.text}))}});
    S.chat = r.chat; S.turn = r.turn;
    await follow(turnState(slot, r.turn, S.mode), 0);
  } catch (e) { settle(slot); slot.m.classList.add("none"); slot.body.append(el("div", "answer", e.message)); }
  setRunning(false); S.turn = null; loadChats(); loadBoard(); loadUsageChip();
}
function turnState(slot, turnId, mode) { return {slot, turn: turnId, steps: slot.steps, cards: {}, cited: new Set(), mode: mode || "manual"}; }
async function follow(st, after) {
  for (let misses = 0; misses < 6;) {
    let r;
    try { r = await api(`/api/turns/${st.turn}?after=${after}`); misses = 0; }
    catch (e) { if (e.status === 404) return; misses++; await sleep(800); continue; }
    for (const e of r.events) {
      handleEvent(st, e, false);
      after = e.i + 1;
      if (e.kind === "end") return;
    }
  }
  failTurn(st, "Lost track of this answer. It may still finish; check Chats in a moment.");
}
function handleEvent(st, e, past) {
  const s = st.slot;
  if (e.kind === "start") {
    for (const [cid, msg] of Object.entries(e.mcp_errors || {})) s.body.insertBefore(el("div", "warnline", `${connName(cid)} isn't available: ${msg}`), s.box);
  } else if (e.kind === "thinking") {
    if (!past) { s.line.textContent = st.mode === "plan" ? "Planning…" : "Thinking…"; s.body.append(s.line); }
  } else if (e.kind === "text") {
    st.steps.append(el("div", "narr", e.text));
    updateHead(st);
  } else if (e.kind === "tool") {
    toolCard(st, e, past);
    if (!past && (e.status === "asking" || e.status === "running")) { s.line.textContent = e.status === "asking" ? "Waiting for you…" : "Working…"; s.body.append(s.line); }
  } else if (e.kind === "browser") {
    if (!past && SIDE.pane !== "browser") openPane("browser");  // the person watches the agent use it
  } else if (e.kind === "answer") {
    finishAnswer(st, e.text, `${shortModel(e.model)} · ${MODES[st.mode].label}${spentLine(e.usage)}`);
  } else if (e.kind === "error") {
    failTurn(st, e.text);
  } else if (e.kind === "end") {
    if (s.body.querySelector(".answer")) s.line.remove();  // after Run plan there's no new answer to replace it
    if (e.planned && !past) planFoot(st, e.planned);
  }
  if (!past) scrollDown();
}
function finishAnswer(st, text, meta) {
  const s = st.slot;
  settle(s, meta);
  const box = el("div", "answer md"); renderMd(box, text || "Done."); s.body.append(box);
  if (st.cited.size) {
    const ids = [...st.cited]; const row = el("div", "row gap");
    row.append(el("span", "badge ok", `${ids.length} event${ids.length > 1 ? "s" : ""} cited`));
    const b = el("button", "evidence-btn", "Show evidence"); b.type = "button";
    b.onclick = () => toggleEvidence(s.body, ids, b);
    row.append(b); s.body.append(row);
    if (HASH.get("evidence")) { HASH.delete("evidence"); setTimeout(() => b.click(), 50); }
  }
}
function failTurn(st, text) {
  const s = st.slot;
  if (!s.line.isConnected && s.body.querySelector(".answer")) return;
  settle(s); s.m.classList.add("none"); s.body.append(el("div", "answer", text));
}

// ---- tool cards: what the agent did, and what waits for you ---------------------------------------------------
const TOOL_UI = {
  team_board: ["board", "Read the board", () => ""],
  team_ask: ["spark", "Asked the team's history", a => a.question],
  team_task: ["board", "Read task", a => a.task],
  team_usage: ["gauge", "Read the team's AI usage", a => (a.days ? `last ${a.days} days` : "")],
  create_task: ["plus", "Create task", a => (a.title || "") + (a.owner ? ` · ${a.owner}` : "")],
  assign_task: ["user", "Assign", a => `${a.task} → ${a.owner}`],
  close_task: ["check", "Close", a => a.task],
  start_task: ["play", "Start on this laptop", a => a.task + (a.repo ? ` in ${a.repo}` : "")],
  list_files: ["folder", "List", a => a.path || "connected repos"],
  read_file: ["file", "Read", a => a.path],
  search_files: ["search", "Search", a => `“${a.query}”${a.path ? ` in ${a.path}` : ""}`],
  write_file: ["edit", "Write", a => a.path],
  run_command: ["term", "Run", a => a.command],
  git_status: ["branch", "Git status", a => a.repo || ""],
  git_branch: ["branch", "Branch", a => a.name],
  git_commit: ["check", "Commit", a => `${(a.message || "").split("\n")[0]}${a.files ? ` · ${a.files.length} file${a.files.length === 1 ? "" : "s"}` : ""}`],
  git_push: ["up", "Push", a => a.repo || "this branch"],
  open_pr: ["github", "Pull request", a => a.title],
  git_pull: ["reload", "Pull", a => a.repo || ""],
  share_files: ["file", "Share", a => `${(a.paths || []).join(", ")} with ${a.to || "everyone"}`],
  share_branch: ["branch", "Hand over the branch", a => `to ${a.to || "everyone"}${a.repo ? ` · ${a.repo}` : ""}`],
  team_files: ["file", "Read what's shared", () => ""],
  take_share: ["file", "Take a share", a => (a.id || "").slice(0, 8) + (a.repo ? ` into ${a.repo}` : "")],
  fetch_url: ["globe", "Read page", a => a.url],
  browser_open: ["globe", "Open", a => a.url],
  browser_snapshot: ["globe", "Read the page", a => (a.find ? `“${a.find}”` : "")],
  browser_click: ["globe", "Click", a => a.ref + (a.double ? " twice" : "")],
  browser_type: ["edit", "Type", a => `“${(a.text || "").slice(0, 40)}” into ${a.ref}${a.submit ? " and submit" : ""}`],
  browser_select: ["globe", "Choose", a => `${a.option} in ${a.ref}`],
  browser_press: ["globe", "Press", a => a.key],
  browser_scroll: ["globe", "Scroll", a => a.ref || a.direction || "down"],
  browser_wait: ["globe", "Wait for", a => a.text || `${a.seconds || 5} s`],
  browser_screenshot: ["globe", "Screenshot", () => ""],
  browser_console: ["term", "Read the console", () => ""],
  browser_eval: ["term", "Run in the page", a => (a.code || "").slice(0, 60)],
  browser_batch: ["list", "Steps", a => `${(a.steps || []).length} in one go`],
  dev_server: ["play", "Dev server", a => `${a.action || "start"}${a.repo ? ` · ${a.repo}` : ""}`],
  desktop_windows: ["laptop", "List windows", () => ""],
  desktop_snapshot: ["laptop", "Read window", a => a.window || (a.find ? `“${a.find}”` : "current")],
  desktop_click: ["laptop", "Press", a => a.ref + (a.mouse ? " with the mouse" : "")],
  desktop_type: ["edit", "Fill", a => `“${(a.text || "").slice(0, 40)}” into ${a.ref}${a.submit ? " and submit" : ""}`],
  desktop_select: ["laptop", "Choose", a => `${a.option} in ${a.ref}`],
  desktop_scroll: ["laptop", "Scroll", a => `${a.ref} ${a.direction || "down"}`],
  desktop_press: ["laptop", "Keys", a => a.keys + (a.window ? ` in ${a.window}` : "")],
  desktop_open: ["play", "Open app", a => a.app],
  desktop_screenshot: ["laptop", "Screenshot", a => a.window || ""],
  desktop_batch: ["list", "Steps", a => `${(a.steps || []).length} in one go`],
  load_skill: ["book", "Use skill", a => a.name],
  read_skill_file: ["book", "Read skill file", a => `${a.name}/${a.file}`],
};
const STATUS = {running: "running", asking: "needs you", planned: "planned", done: "✓ done", failed: "✕ failed", declined: "declined",
  discarded: "discarded", undone: "undone"};
const connName = cid => (S.connectors.find(c => c.id === cid) || {}).name || cid;
const argText = a => Object.entries(a || {}).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(", ").slice(0, 200);
function toolUi(e) {
  if (TOOL_UI[e.name]) return TOOL_UI[e.name];
  const m = /^mcp__.+?__(.+)$/.exec(e.name);
  const conn = (e.group || "").startsWith("mcp:") ? connName(e.group.slice(4)) : "Connector";
  return ["plug", m ? `${conn} · ${m[1]}` : e.name, argText];
}
function toolCard(st, e, past) {
  let c = st.cards[e.id];
  if (!c) {
    const [iconName, label, describe] = toolUi(e);
    const box = el("div", "tool"); const row = el("div", "tool-row");
    const tic = el("span", "tic"); tic.innerHTML = icon(iconName);
    const what = describe(e.args || {}) || "";
    let target;
    if (["read_file", "write_file"].includes(e.name) && what) { target = el("button", "tlink", what); target.type = "button"; target.onclick = ev => { ev.stopPropagation(); openFile(what); }; }
    else if (["fetch_url", "browser_open"].includes(e.name) && /^https?:/.test(what)) { target = el("button", "tlink", what); target.type = "button"; target.onclick = ev => { ev.stopPropagation(); openBrowser(what); }; }
    else target = el("span", "targ", what);
    const tst = el("button", "tst"); tst.type = "button"; tst.setAttribute("aria-expanded", "false");
    row.append(tic, el("b", null, label), target, tst);
    box.append(row); st.steps.append(box);
    c = st.cards[e.id] = {box, row, tst, e, out: null, result: null, target};
    const toggle = () => toggleOut(c);
    row.onclick = toggle; tst.onclick = ev => { ev.stopPropagation(); toggle(); };
  }
  c.e = {...c.e, ...e};
  setCard(c, e.status, st, past);
  if (e.result != null) { c.result = e.result; if (c.out) c.out.textContent = e.result; }
  // "Press ref_12" says nothing to a person: once the step is done, show what it pressed ("menuitem “File”")
  const did = /^(desktop|browser)_(click|type|select|scroll)$/.test(e.name) && /^(?:Pressed|Clicked|Filled|Typed into|Chose|Scrolled) (.+)\.$/m.exec((c.result || "").split("\n")[0]);
  if (did && c.target) c.target.textContent = did[1];
  const shot = /^(browser|desktop)_screenshot$/.test(e.name) && /\[screenshot ((sh|dk)_[0-9a-f]{10})\]/.exec(c.result || "");
  if (shot && !c.img) {  // the proof, in the chat: the person sees what the agent checked
    c.img = el("img", "tshot"); c.img.alt = shot[2] === "sh" ? "Screenshot of the page" : "Screenshot of the window"; c.box.append(c.img);
    fetch(`/api/${shot[2] === "sh" ? "browser" : "desktop"}/shot/${shot[1]}`, {headers: {"X-App-Key": KEY}}).then(r => (r.ok ? r.blob() : null))
      .then(b => { if (b) c.img.src = URL.createObjectURL(b); else c.img.remove(); }).catch(() => c.img.remove());
  }
  if (e.status === "done" && e.name === "team_ask") for (const id of e.citations || []) st.cited.add(id);
  if (e.status === "done" && !past) undoable(c, st);
  if (e.status === "done" && !past && e.name === "write_file" && FILES.current === (e.args || {}).path) openFile(FILES.current);
}
function setCard(c, status, st, past) {
  c.status = status;
  c.box.className = `tool ${status}`;
  c.tst.replaceChildren();
  if (status === "running") c.tst.append(el("span", "spin"));
  c.tst.append(STATUS[status] || status);
  c.box.querySelector(".ask-box")?.remove();
  if (status === "asking" && !past) c.box.append(askBox(c, st));
  // waiting for the person: in view; anything else: folded into the steps
  const home = !past && (status === "asking" || status === "planned") ? st.slot.needs : st.steps;
  if (c.box.parentElement !== home) home.append(c.box);
  updateHead(st);
}
function toggleOut(c) {
  if (!c.result) return;
  if (c.out) { c.out.remove(); c.out = null; c.tst.setAttribute("aria-expanded", "false"); return; }
  c.out = el("pre", "tout", c.result);
  c.box.insertBefore(c.out, c.box.querySelector(".ask-box")); c.tst.setAttribute("aria-expanded", "true");
}
function askBox(c, st) {
  const e = c.e; const a = e.args || {}; const who = st.slot.agent.name;
  const box = el("div", "ask-box");
  if (e.name === "run_command") box.append(el("p", null, `${who} wants to run this on your laptop${a.cwd ? ` in ${a.cwd}` : ""}:`), el("pre", null, a.command || ""));
  else if (e.name === "write_file") box.append(el("p", null, `${who} wants to write ${a.path}:`), el("pre", null, (a.content || "").slice(0, 6000)));
  else if (e.name === "git_commit") box.append(el("p", null, `${who} wants to commit these files on the current branch:`), el("pre", null, `${a.message || ""}\n\n${(a.files || []).join("\n")}`));
  else if (e.name === "git_push") box.append(el("p", null, `${who} wants to push the current branch${a.repo ? ` of ${a.repo}` : ""} to GitHub, with your sign-in. Your team will see it there.`));
  else if (e.name === "open_pr") box.append(el("p", null, `${who} wants to open a pull request${a.base ? ` into ${a.base}` : ""}:`), el("pre", null, `${a.title || ""}\n\n${a.body || ""}`));
  else if ((e.group || "").startsWith("mcp:")) box.append(el("p", null, `${who} wants to use ${toolUi(e)[1]} with:`), el("pre", null, JSON.stringify(a, null, 2)));
  else if (e.name === "browser_open") box.append(el("p", null, `${who} wants to open ${a.url} in the browser you share.`));
  else if (e.name === "browser_eval") box.append(el("p", null, `${who} wants to run this in the page:`), el("pre", null, a.code || ""));
  else if (e.name === "share_files") box.append(el("p", null, `${who} wants to share these with ${a.to || "the whole team"}. They leave this laptop and are kept 14 days:`), el("pre", null, (a.paths || []).join("\n") + (a.note ? `\n\n${a.note}` : "")));
  else if (e.name === "share_branch") box.append(el("p", null, `${who} wants to hand the current branch${a.repo ? ` of ${a.repo}` : ""} over to ${a.to || "the whole team"}${a.note ? `: “${a.note}”` : "."}`));
  else if (e.name === "take_share") box.append(el("p", null, `${who} wants to take share ${(a.id || "").slice(0, 8)}: save its files into ${a.repo || "your repo"}'s inbox, or check out the branch it hands over.`));
  else if (e.name === "dev_server") box.append(el("p", null, `${who} wants to ${a.action === "stop" ? "stop" : "start"} the dev server of ${a.repo || "your repo"} (its launch.json or dev script).`));
  else if (e.name === "desktop_open") box.append(el("p", null, `${who} wants to open ${a.app} on this laptop and work in its window.`));
  else if (e.name.startsWith("desktop_") && e.access === "ask") box.append(el("p", null, `${who} wants to use ${a.window || "this app"}: read its window and act in it through its controls.`));
  else if (e.name.startsWith("desktop_")) box.append(el("p", null, `${who} wants to ${toolUi(e)[1].toLowerCase()} ${toolUi(e)[2](a) || ""}${e.name === "desktop_press" || a.mouse || a.keys ? " (this brings the window forward for a moment)" : ""}.`));
  else if (e.name.startsWith("browser_")) box.append(el("p", null, `${who} wants to ${toolUi(e)[1].toLowerCase()} ${toolUi(e)[2](a) || ""} on ${BR.state.url || "this page"}.`));
  else box.append(el("p", null, `${who} wants to make this change.`));
  const row = el("div", "row gap");
  const no = el("button", "btn small ghost", "Deny"), yes = el("button", "btn small primary", e.name === "run_command" ? "Run it" : "Allow");
  no.type = yes.type = "button";
  const decide = async ok => {
    no.disabled = yes.disabled = true;
    try { await api(`/api/turns/${st.turn}/decide`, {method: "POST", body: {call: e.id, approve: ok}}); }
    catch (err) { toast(err.message, true); no.disabled = yes.disabled = false; }
  };
  no.onclick = () => decide(false); yes.onclick = () => decide(true);
  // a site agents haven't been allowed on: once, or always (Settings → Privacy lists the sites)
  let site = "";
  if (e.access === "ask" && e.name.startsWith("browser_") && e.name !== "browser_eval") {
    try { site = new URL(/^https?:/.test(a.url || "") ? a.url : BR.state.url).hostname; } catch (err) { site = ""; }
  }
  if (site) {
    const always = el("button", "btn small", `Always allow ${site}`); always.type = "button";
    always.onclick = async () => {
      try { await api("/api/browser/sites", {method: "POST", body: {site, allowed: true}}); } catch (err) { toast(err.message, true); return; }
      decide(true);
    };
    yes.textContent = "Allow once"; row.append(no, always, yes);
  } else row.append(no, yes);
  if (e.access === "ask" && e.name.startsWith("desktop_") && e.name !== "desktop_open") {  // an app agents haven't used yet
    api("/api/desktop/state").then(d => {
      if (!d.pending || !row.isConnected) return;
      const always = el("button", "btn small", `Always allow ${d.pending}`); always.type = "button";
      always.onclick = async () => {
        try { await api("/api/desktop/apps", {method: "POST", body: {site: d.pending, allowed: true}}); } catch (err) { toast(err.message, true); return; }
        decide(true);
      };
      yes.textContent = "Allow once"; row.insertBefore(always, yes);
    }).catch(() => {});
  }
  box.append(row);
  return box;
}
// Undo for the board changes that can be put back exactly.
function undoable(c, st) {
  const e = c.e; let put;
  const made = /^Created ([A-Z][A-Z0-9]*-\d+)/.exec(c.result || "");
  if (e.name === "create_task" && made) put = () => hub(withTeam(`tasks/${encodeURIComponent(made[1])}`), {method: "DELETE"});
  if (e.name === "close_task") put = () => hub(withTeam(`tasks/${encodeURIComponent(e.args.task)}`), {method: "PATCH", body: {state: "open"}});
  if (!put) return;
  const u = el("button", "link-btn", "Undo"); u.type = "button";
  u.onclick = async ev => {
    ev.stopPropagation(); u.disabled = true;
    try { await put(); setCard(c, "undone", st, true); loadBoard(); } catch (err) { toast(err.message, true); u.disabled = false; }
  };
  c.row.append(u);
}
function planFoot(st, n) {
  const box = el("div", "plan-foot");
  const t = el("span"); t.append(el("b", null, `${n} change${n > 1 ? "s" : ""} planned.`), " Nothing has changed yet.");
  const no = el("button", "btn small ghost", "Discard"); no.type = "button";
  const runBtn = el("button", "btn small primary"); runBtn.type = "button"; runBtn.append(ic("play"), "Run plan");
  no.onclick = () => {
    for (const c of Object.values(st.cards)) if (c.status === "planned") setCard(c, "discarded", st, true);
    box.replaceChildren(el("span", null, "Plan discarded. Nothing changed."));
  };
  runBtn.onclick = async () => {
    if (S.running) return;
    runBtn.disabled = no.disabled = true; setRunning(true); S.turn = st.turn;
    try { const r = await api(`/api/turns/${st.turn}/run-plan`, {method: "POST"}); box.remove(); await follow(st, r.after); toast("Plan applied."); }
    catch (e) { toast(e.message, true); runBtn.disabled = no.disabled = false; }
    setRunning(false); S.turn = null; loadBoard();
  };
  box.append(t, no, runBtn); st.slot.body.append(box); scrollDown();
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
    const plan = body.querySelector(".plan-foot");
    if (plan) body.insertBefore(box, plan); else body.append(box);
    btn.textContent = "Hide evidence"; scrollDown();
  } catch (e) { toast(e.message, true); }
  btn.disabled = false;
}

async function digest() {
  if (!S.team || S.running) return;
  userMsg("Today's digest");
  const slot = agentMsg(S.agents.find(a => a.id === "agent-s") || currentAgent());
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

// ---- the composer: agent, import, mode, model ------------------------------------------------------------------
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
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!S.running) $("askForm").requestSubmit(); }
  if (e.key === "Tab" && e.shiftKey) { e.preventDefault(); setMode(MODE_ORDER[(MODE_ORDER.indexOf(S.mode) + 1) % MODE_ORDER.length]); }
});
$("askForm").addEventListener("submit", e => {
  e.preventDefault();
  if (S.running) { if (S.turn) api(`/api/turns/${S.turn}/cancel`, {method: "POST"}).catch(() => {}); return; }  // the stop button
  const q = askIn.value.trim(); if (!q) return;
  askIn.value = ""; askIn.style.height = "auto"; ask(q);
});
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
    const foot = el("div", "card-foot"); const due = dueChip(t.due, t.status); if (due) foot.append(due);
    foot.append(el("span", null, `planned ${ago(t.last_activity)}`)); c.append(foot);
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
  const due = dueChip(t.due, t.status); if (due) foot.append(due);
  if (t.owner && !t.members.includes(t.owner)) foot.append(el("span", "tag", `owner ${t.owner}`));
  for (const m of t.members) foot.append(el("span", "tag", m));
  for (const tool of t.tools) if (TOOLS[tool]) foot.append(el("span", "tag", TOOLS[tool]));
  if (t.pr) foot.append(el("span", "tag pr", [`PR #${t.pr.number}`, t.pr.draft ? "draft" : t.pr.state, t.pr.checks ? `CI ${t.pr.checks}` : ""].filter(Boolean).join(" · ")));
  if (t.usage && t.usage.tokens) { const u = el("span", "tag", `${fmtTok(t.usage.tokens)} tokens`); u.title = `${t.usage.turns} turns of AI coding on ${t.task}`; foot.append(u); }
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

const fmtDate = d => new Date(`${d}T00:00:00`).toLocaleDateString([], {month: "short", day: "numeric"});
function dueChip(due, status) {
  if (!due) return null;
  const today = new Date(new Date().toDateString());
  const days = Math.round((new Date(`${due}T00:00:00`) - today) / 86400000);
  const open = status !== "done";
  const label = !open ? `Due ${fmtDate(due)}` : days < 0 ? `${-days} day${days === -1 ? "" : "s"} late` : days === 0 ? "Due today"
    : days === 1 ? "Due tomorrow" : `Due ${fmtDate(due)}`;
  const t = el("span", "tag due" + (open && days < 0 ? " late" : open && days <= 1 ? " soon" : ""), label); t.title = `Deadline ${due}`;
  return t;
}

// ---- the drawer: task timelines, and the agent, skill and connector editors ----------------------------------
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
function openDrawer(kicker, title, nodes, foot) {
  openedFrom = document.activeElement;
  $("dFoot").classList.remove("compose");
  $("dId").textContent = kicker; $("dTitle").textContent = title;
  $("dBody").replaceChildren(...nodes); $("dBody").scrollTop = 0;
  $("dFoot").replaceChildren(...(foot || [])); $("dFoot").hidden = !(foot && foot.length);
  $("scrim").hidden = false; $("drawer").hidden = false;
}
async function openTask(task, highlight) {
  try {
    const d = await hub(withTeam(`tasks/${encodeURIComponent(task)}`));
    const nodes = [sparkline(d.history || [])];
    if (d.usage && d.usage.tokens) nodes.push(el("div", "label", `AI usage · ${fmtTok(d.usage.tokens)} tokens over ${d.usage.turns} turns`));
    const dueRow = el("div", "due-row"); const di = inputEl({type: "date", value: d.due || ""}); di.setAttribute("aria-label", "Deadline");
    di.onchange = async () => {
      try { await hub(withTeam(`tasks/${encodeURIComponent(d.task)}`), {method: "PATCH", body: {due: di.value || ""}});
        toast(di.value ? `${d.task} is due ${fmtDate(di.value)}.` : `${d.task} has no deadline now.`); loadBoard(); }
      catch (e) { toast(e.message, true); }
    };
    dueRow.append(el("span", "label", "Deadline"), di); const chip = dueChip(d.due, d.status); if (chip) dueRow.append(chip);
    nodes.push(dueRow);
    const p = d.progress || {}; const lists = el("div", "lists");
    for (const r of [list("Blocked", p.blockers, "blockers"), list("Done", p.done), list("Doing", p.doing), list("Next", p.next)]) if (r) lists.append(r);
    if (lists.childElementCount) nodes.push(lists);
    nodes.push(el("div", "label", "Timeline, newest first"));
    if (!d.timeline.length) nodes.push(el("p", "sub", d.owner ? `Planned for ${d.owner}. When a session starts on ${d.task}, it shows up here.`
      : `Planned. When someone starts a session on ${d.task}, it shows up here.`));
    const ol = el("ol", "timeline"); const hit = new Set(highlight || []);
    for (const e of d.timeline) {
      const li = el("li", hit.has(e.id) ? "hit" : null); const t = el("div");
      t.append(el("b", null, `${e.member}${TOOLS[e.tool] ? " · " + TOOLS[e.tool] : ""}  `), e.line);
      li.append(el("time", null, clock(e.ts)), t); ol.append(li);
    }
    nodes.push(ol);
    openDrawer(d.task, d.title || d.task, nodes);
    $("dClose").focus();
    const first = ol.querySelector(".hit"); if (first) first.scrollIntoView({block: "center"});
  } catch (e) { toast(e.message, true); }
}
function closeDrawer() { $("drawer").hidden = true; $("scrim").hidden = true; if (openedFrom && openedFrom.isConnected) openedFrom.focus(); }
$("dClose").onclick = closeDrawer; $("scrim").onclick = closeDrawer;

// small form pieces for the editors
function fieldBox(label, control, hint) { const l = el("label", "field"); l.append(el("span", null, label), control); if (hint) l.append(el("span", "hint", hint)); return l; }
function groupBox(label, control, hint) { const d = el("div", "field"); d.setAttribute("role", "group"); d.setAttribute("aria-label", label); d.append(el("span", null, label), control); if (hint) d.append(el("span", "hint", hint)); return d; }
function inputEl(props) { return Object.assign(el("input"), props); }
function textareaEl(props) { return Object.assign(el("textarea"), props); }
function segEl(options, value, onPick) {
  const s = el("div", "seg");
  for (const [k, label] of options) {
    const b = el("button", null, label); b.type = "button"; b.setAttribute("aria-pressed", String(k === value));
    b.onclick = () => { for (const x of s.children) x.setAttribute("aria-pressed", "false"); b.setAttribute("aria-pressed", "true"); onPick(k); };
    s.append(b);
  }
  return s;
}
function optEl(checked, title, small, tag) {
  const l = el("label", "opt"); const c = inputEl({type: "checkbox", checked});
  const w = el("span"); const b = el("b", null, title); if (tag) b.append(tag); w.append(b); if (small) w.append(el("small", null, small));
  l.append(c, w); return {l, c};
}
function btn(label, cls, onClick, iconName) { const b = el("button", `btn small ${cls || ""}`); b.type = "button"; if (iconName) b.append(ic(iconName)); b.append(label); b.onclick = onClick; return b; }
function armed(label, onConfirm) {  // a destructive button that asks for a second click
  const b = btn(label, "ghost", () => {
    if (b.dataset.armed) return onConfirm();
    b.dataset.armed = "1"; b.textContent = `${label}: click again`; b.classList.add("danger");
    setTimeout(() => { delete b.dataset.armed; b.textContent = label; b.classList.remove("danger"); }, 3000);
  });
  return b;
}

// ---- Agents page: agents, skills, connectors --------------------------------------------------------------------
let agentTab = "agents";
const TAB_SUB = {
  agents: "Each agent has its own instructions, model, mode, skills, connectors and tools.",
  skills: "Skills teach agents a way of working. An agent reads a skill when the task calls for it; always-on skills are part of every message.",
  connectors: "Connectors are MCP servers, as in Claude Desktop. Give one to an agent and it can use that server's tools.",
  memory: "Agents remember notes you or they save, and can search what happened before, across chats and projects.",
};
function showAgentTab(tab) {
  agentTab = tab;
  for (const b of $("agentTabs").children) b.classList.toggle("on", b.dataset.tab === tab);
  for (const t of Object.keys(TAB_SUB)) $(`tab-${t}`).hidden = t !== tab;
  $("agentsSub").textContent = TAB_SUB[tab];
  if (tab === "agents") renderAgents();
  if (tab === "skills") renderSkills();
  if (tab === "connectors") renderConnectors();
  if (tab === "memory") renderMemory();
}
for (const b of $("agentTabs").children) b.onclick = () => showAgentTab(b.dataset.tab);

async function renderAgents() {
  await loadAgents();
  const grid = $("tab-agents"); grid.className = "tab agent-grid"; grid.replaceChildren();
  S.agents.forEach((a, i) => {
    const c = el("article", "agent-card"); c.style.animationDelay = `${Math.min(i, 8) * 40}ms`;
    const head = el("div", "head"); const words = el("div"); words.style.minWidth = "0";
    words.append(el("h3", null, a.name), el("div", "meta", `${a.model === "auto" ? "Auto model" : MODELS[a.model].label} · ${MODES[a.mode].label} mode${a.builtin ? " · built in" : ""}`));
    head.append(agent("", a.color), words);
    const chips = el("div", "row");
    const n = a.skills.length, k = a.connectors.length;
    chips.append(el("span", "tag", `${n} skill${n === 1 ? "" : "s"}`), el("span", "tag", `${k} connector${k === 1 ? "" : "s"}`));
    for (const g of Object.keys(TOOL_GROUPS)) if (a.tools[g]) chips.append(el("span", "tag", TOOL_GROUPS[g].label));
    const foot = el("div", "foot");
    foot.append(btn("Chat", "ghost", () => { setAgent(a.id); newChat(); }), btn("Edit", "", () => editAgent(a)));
    c.append(head, el("p", "instr", agentLine(a)), chips, foot); grid.append(c);
  });
  const add = el("button", "agent-card add"); add.type = "button";
  add.append(ic("plus"), el("b", null, "New agent"), el("span", "sub", "A reviewer, a release manager, a researcher: give it instructions, skills and tools."));
  add.onclick = () => editAgent(null);
  grid.append(add);
}
async function editAgent(a) {
  const isNew = !a;
  const draft = a ? JSON.parse(JSON.stringify(a)) : {name: "", color: S.colors[S.agents.length % S.colors.length] || "#3E9B6B", instructions: "",
    model: "auto", mode: "manual", skills: ["karpathy-guidelines"], connectors: [], tools: {team: true, files: true, terminal: true, browser: true}};
  const [skills, conns] = await Promise.all([api("/api/skills").then(r => r.skills).catch(() => []), api("/api/connectors").then(r => r.items).catch(() => [])]);
  const name = inputEl({value: draft.name, maxLength: 40, placeholder: "e.g. Reviewer", required: true});
  const sw = el("div", "swatches");
  for (const c of S.colors) {
    const b = el("button"); b.type = "button"; b.style.setProperty("--c", c); b.setAttribute("aria-label", `Hood colour ${c}`); b.setAttribute("aria-pressed", String(c === draft.color));
    b.onclick = () => { draft.color = c; for (const x of sw.children) x.setAttribute("aria-pressed", String(x === b)); };
    sw.append(b);
  }
  const instr = textareaEl({value: draft.instructions, maxLength: 8000, rows: 8,
    placeholder: "How should this agent work? For example: You review pull requests like a staff engineer. Correctness first, then tests, then naming. Be blunt and specific; quote the line you mean."});
  const tools = el("div", "opts");
  for (const [g, t] of Object.entries(TOOL_GROUPS)) { const o = optEl(!!draft.tools[g], t.label, t.desc); o.c.onchange = () => { draft.tools[g] = o.c.checked; }; tools.append(o.l); }
  const sk = el("div", "opts");
  for (const s of skills) {
    const o = optEl(draft.skills.includes(s.name), s.name, s.description, s.always ? el("span", "pill-tag on", "in every message") : null);
    o.c.onchange = () => { draft.skills = o.c.checked ? [...new Set([...draft.skills, s.name])] : draft.skills.filter(x => x !== s.name); };
    sk.append(o.l);
  }
  const cn = el("div", "opts");
  for (const c of conns) {
    const o = optEl(draft.connectors.includes(c.id), c.name, c.kind === "http" ? c.url : [c.command, ...(c.args || [])].join(" "), c.enabled ? null : el("span", "pill-tag", "off"));
    o.c.onchange = () => { draft.connectors = o.c.checked ? [...new Set([...draft.connectors, c.id])] : draft.connectors.filter(x => x !== c.id); };
    cn.append(o.l);
  }
  if (!conns.length) { const p = el("p", "sub"); p.append("No connectors yet. "); const l = el("button", "link-btn", "Add one"); l.type = "button"; l.onclick = () => { closeDrawer(); showAgentTab("connectors"); }; p.append(l); cn.append(p); }
  const form = el("form", "form");
  form.append(fieldBox("Name", name), groupBox("Hood", sw),
    fieldBox("Instructions", instr, "Its behaviour: role, tone, what to check, what never to do. Added to every message."),
    groupBox("Default model", segEl(Object.keys(MODELS).map(k => [k, MODELS[k].label.replace("Nemotron ", "")]), draft.model, k => { draft.model = k; })),
    groupBox("Default mode", segEl(MODE_ORDER.map(k => [k, MODES[k].label]), draft.mode, k => { draft.mode = k; })),
    groupBox("Tools", tools), groupBox("Skills", sk, "Karpathy's guidelines are on by default: think first, keep it simple, change only what's asked."),
    groupBox("Connectors", cn));
  const save = async () => {
    if (!name.value.trim()) { name.focus(); return toast("Give the agent a name.", true); }
    const body = {name: name.value.trim(), color: draft.color, instructions: instr.value, model: draft.model, mode: draft.mode,
      skills: draft.skills, connectors: draft.connectors, tools: draft.tools};
    try {
      const saved = await api(isNew ? "/api/agents" : `/api/agents/${a.id}`, {method: isNew ? "POST" : "PATCH", body});
      closeDrawer(); toast(isNew ? `${saved.name} is ready.` : `Saved ${saved.name}.`);
      await renderAgents(); renderChats();
    } catch (e) { toast(e.message, true); }
  };
  form.addEventListener("submit", e => { e.preventDefault(); save(); });
  const foot = [];
  if (!isNew && !a.builtin) foot.push(armed("Delete", async () => {
    try { await api(`/api/agents/${a.id}`, {method: "DELETE"}); closeDrawer(); if (S.agent === a.id) setAgent("agent-s"); toast(`Deleted ${a.name}.`); renderAgents(); }
    catch (e) { toast(e.message, true); }
  }));
  foot.push(el("span", "grow"), btn("Cancel", "ghost", closeDrawer), btn(isNew ? "Create agent" : "Save", "primary", save));
  openDrawer(isNew ? "Agents" : a.builtin ? "Built-in agent" : "Agent", isNew ? "New agent" : a.name, [form], foot);
  name.focus();
}

async function renderSkills() {
  const box = $("tab-skills"); box.replaceChildren(el("div", "skeleton"));
  let skills;
  try { skills = (await api("/api/skills")).skills; } catch (e) { box.replaceChildren(el("p", "err", e.message)); return; }
  const bar = el("div", "bar");
  bar.append(btn("New skill", "primary", () => editSkill(null), "plus"), btn("Import from Claude Code", "", importSkills, "book"));
  const rows = el("div", "list");
  skills.forEach((s, i) => {
    const it = el("div", "item"); it.style.animationDelay = `${Math.min(i, 8) * 30}ms`;
    const iic = el("span", "iic"); iic.append(ic("book"));
    const w = el("div"); const nm = el("b", "mono", s.name);
    if (s.always) nm.append(el("span", "pill-tag on", "in every message"));
    nm.append(el("span", "pill-tag", s.bundled ? "built in" : "yours"));
    w.append(nm, el("small", null, s.description || "No description"));
    const ctl = el("div", "ctl"); ctl.append(btn("Open", "ghost", () => viewSkill(s.name)));
    it.append(iic, w, ctl); rows.append(it);
  });
  box.replaceChildren(bar, rows);
}
async function viewSkill(name) {
  let s;
  try { s = await api(`/api/skills/${encodeURIComponent(name)}`); } catch (e) { return toast(e.message, true); }
  const md = el("div", "md"); renderMd(md, s.body);
  const nodes = [el("p", "sub", s.description), md];
  if (s.files.length) nodes.push(el("div", "label", `Also in this skill: ${s.files.join(", ")}`));
  const foot = [];
  if (!s.bundled) foot.push(armed(s.name === "karpathy-guidelines" ? "Reset to built in" : "Delete", async () => {
    try { await api(`/api/skills/${encodeURIComponent(s.name)}`, {method: "DELETE"}); closeDrawer(); toast(`Removed ${s.name}.`); renderSkills(); }
    catch (e) { toast(e.message, true); }
  }));
  foot.push(el("span", "grow"), btn(s.bundled ? "Customize" : "Edit", "", () => editSkill(s), "edit"));
  openDrawer(s.bundled ? "Built-in skill" : "Your skill", s.name, nodes, foot);
}
function editSkill(s) {
  const isNew = !s;
  const name = inputEl({value: s ? s.name : "", maxLength: 64, placeholder: "e.g. release-notes", className: "mono", disabled: !isNew});
  const desc = inputEl({value: s ? s.description : "", maxLength: 400, placeholder: "When to use it, in one line. Agents decide from this."});
  const body = textareaEl({value: s ? s.body : "", rows: 18, className: "mono", placeholder: "# Release notes\n\nGroup merged work by feature. Lead with what users notice…"});
  const save = async () => {
    try {
      const r = await api("/api/skills", {method: "POST", body: {name: name.value.trim(), description: desc.value.trim(), body: body.value}});
      closeDrawer(); toast(`Saved ${r.name}. Turn it on for an agent in Agents.`); renderSkills();
    } catch (e) { toast(e.message, true); }
  };
  const form = el("form", "form");
  form.append(fieldBox("Name", name, "Lowercase letters, digits and dashes."), fieldBox("Description", desc), fieldBox("Instructions (SKILL.md)", body, "Markdown. Claude Code's skill format, so the same skill works in both."));
  form.addEventListener("submit", e => { e.preventDefault(); save(); });
  openDrawer(isNew ? "New skill" : s.bundled ? "Your copy of a built-in skill" : "Edit skill", isNew ? "New skill" : s.name, [form],
    [el("span", "grow"), btn("Cancel", "ghost", closeDrawer), btn("Save skill", "primary", save)]);
  (isNew ? name : body).focus();
}
async function importSkills() {
  let found;
  try { found = (await api("/api/skills/claude-code")).skills; } catch (e) { return toast(e.message, true); }
  const rows = el("div", "list");
  for (const s of found) {
    const it = el("div", "item"); const iic = el("span", "iic"); iic.append(ic("book"));
    const w = el("div"); w.append(el("b", "mono", s.name), el("small", null, s.description || ""));
    const ctl = el("div", "ctl");
    const b = btn(s.installed ? "Import again" : "Import", s.installed ? "ghost" : "primary", async () => {
      b.disabled = true;
      try { await api("/api/skills/import", {method: "POST", body: {name: s.name}}); b.textContent = "Added"; renderSkills(); }
      catch (e) { toast(e.message, true); b.disabled = false; }
    });
    ctl.append(b); it.append(iic, w, ctl); rows.append(it);
  }
  openDrawer("Claude Code", "Import skills", [el("p", "sub", "Skills installed for Claude Code on this laptop (~/.claude/skills). Importing copies one into Super Agents."),
    found.length ? rows : el("p", "sub", "No Claude Code skills found on this laptop.")]);
}

async function renderConnectors() {
  const box = $("tab-connectors");
  let r;
  try { r = await api("/api/connectors"); S.connectors = r.items; } catch (e) { box.replaceChildren(el("p", "err", e.message)); return; }
  const rows = el("div", "list");
  for (const c of r.items) rows.append(connectorItem(c, r));
  if (!r.items.length) rows.append(el("p", "sub", "None yet. Add one below, then switch it on for an agent."));
  const presets = el("div", "presets");
  for (const p of r.presets) presets.append(presetCard(p));
  presets.append(customCard());
  box.replaceChildren(el("h3", "section-title", "Your connectors"), rows, el("h3", "section-title", "Add a connector"), presets);
}
function connectorItem(c, r) {
  const it = el("div", "item" + (c.enabled ? "" : " off"));
  const iic = el("span", "iic"); iic.append(ic("plug"));
  const w = el("div"); const nm = el("b", null, c.name);
  nm.append(el("span", "pill-tag", c.kind === "http" ? "http" : "local"));
  if (r.live[c.id] != null) nm.append(el("span", "pill-tag on", `${r.live[c.id]} tools`));
  if (r.errors[c.id]) nm.append(el("span", "pill-tag bad", "error"));
  const users = S.agents.filter(a => a.connectors.includes(c.id)).map(a => a.name);
  w.append(nm, el("small", null, c.kind === "http" ? c.url : [c.command, ...(c.args || [])].join(" ")),
    el("small", null, users.length ? `Used by ${users.join(", ")}` : "No agent uses it yet"));
  const msg = el("div", "err", r.errors[c.id] || ""); w.append(msg);
  const tg = el("button", "toggle"); tg.type = "button"; tg.setAttribute("role", "switch"); tg.setAttribute("aria-checked", String(!!c.enabled)); tg.setAttribute("aria-label", `${c.name} on`);
  tg.onclick = async () => { await api(`/api/connectors/${c.id}`, {method: "PATCH", body: {enabled: !c.enabled}}).catch(e => toast(e.message, true)); renderConnectors(); };
  const test = btn("Test", "ghost", async () => {
    test.disabled = true; msg.className = "sub"; msg.textContent = "Connecting…";
    try { const t = (await api(`/api/connectors/${c.id}/test`, {method: "POST"})).tools; msg.textContent = `Works. ${t.length} tools: ${t.slice(0, 8).join(", ")}${t.length > 8 ? ", …" : ""}`; }
    catch (e) { msg.className = "err"; msg.textContent = e.message; }
    test.disabled = false;
  });
  const del = armed("Remove", async () => { await api(`/api/connectors/${c.id}`, {method: "DELETE"}).catch(e => toast(e.message, true)); await loadAgents(); renderConnectors(); });
  const ctl = el("div", "ctl"); ctl.append(tg, test, del);
  it.append(iic, w, ctl); return it;
}
async function addConnector(body, give, msg) {
  try {
    const c = await api("/api/connectors", {method: "POST", body});
    if (give) { const s = S.agents.find(a => a.id === "agent-s"); await api("/api/agents/agent-s", {method: "PATCH", body: {connectors: [...new Set([...(s ? s.connectors : []), c.id])]}}); }
    toast(`Added ${c.name}.${give ? " Agent S can use it now." : ""}`);
    await loadAgents(); renderConnectors();
  } catch (e) { msg.textContent = e.message; }
}
function giveBox() { const o = optEl(true, "Give it to Agent S", null); o.l.style.padding = "6px 10px"; return o; }
function presetCard(p) {
  const box = el("div", "preset"); const h = el("h4"); h.append(ic("plug"), p.name);
  box.append(h, el("p", null, p.about));
  const values = {};
  for (const f of p.fields) {
    const i = inputEl({type: f.secret ? "password" : "text", placeholder: f.label, autocomplete: "off", className: f.arg ? "mono" : ""});
    i.oninput = () => { values[f.key] = i.value; };
    if (f.arg) {
      const row = el("div", "row gap"); i.style.flex = "1";
      row.append(i, btn("Pick", "ghost", async () => { const r = await api("/api/pick-folder", {method: "POST"}).catch(() => ({})); if (r.path) { i.value = r.path; values[f.key] = r.path; } }));
      box.append(row);
    } else box.append(i);
  }
  const give = giveBox(); const msg = el("div", "err");
  box.append(give.l, btn("Add", "primary", () => { msg.textContent = ""; addConnector({preset: p.preset, values}, give.c.checked, msg); }, "plus"), msg);
  return box;
}
function customCard() {
  const box = el("div", "preset"); const h = el("h4"); h.append(ic("plug"), "Custom MCP server");
  box.append(h, el("p", null, "Any MCP server: a URL (streamable HTTP) or a command this laptop runs (stdio)."));
  let kind = "url";
  const name = inputEl({placeholder: "Name", maxLength: 40});
  const url = inputEl({placeholder: "https://example.com/mcp", className: "mono"});
  const header = inputEl({placeholder: "Authorization header (optional)", type: "password", autocomplete: "off"});
  const cmd = inputEl({placeholder: "Command, e.g. npx or uvx", className: "mono"});
  const args = textareaEl({placeholder: "Arguments, one per line", rows: 3, className: "mono"});
  const urlBox = el("div", "stack"); urlBox.append(url, header);
  const cmdBox = el("div", "stack"); cmdBox.append(cmd, args); cmdBox.hidden = true;
  const seg = segEl([["url", "URL"], ["command", "Command"]], kind, k => { kind = k; urlBox.hidden = k !== "url"; cmdBox.hidden = k !== "command"; });
  const give = giveBox(); const msg = el("div", "err");
  box.append(name, seg, urlBox, cmdBox, give.l, btn("Add", "primary", () => {
    msg.textContent = "";
    const body = kind === "url" ? {name: name.value, url: url.value.trim(), headers: header.value.trim() ? {Authorization: header.value.trim()} : {}}
      : {name: name.value, command: cmd.value.trim(), args: args.value.split("\n").map(x => x.trim()).filter(Boolean)};
    addConnector(body, give.c.checked, msg);
  }, "plus"), msg);
  return box;
}

// ---- memory: notes, and recall over earlier chats and this laptop's coding sessions ---------------------------
async function renderMemory() {
  const box = $("tab-memory");
  let m;
  try { m = await api("/api/memory"); } catch (e) { box.replaceChildren(el("p", "err", e.message)); return; }
  const st = m.stats;
  const intro = el("p", "intro", "Agents keep short notes (a preference, a decision, how a project works) and see them in every chat. They can also search what happened before: earlier chats here and your Claude Code and Codex sessions in every project on this laptop, the prompts and replies, never tool output. The index stays on this laptop; what a search finds goes to the model like any tool's result, with secrets hidden.");
  const sw = el("div", "switch");
  const words = el("div"); words.append(el("b", null, "Search my Claude Code and Codex sessions"),
    el("small", null, m.settings.sessions ? `${st.session_passages.toLocaleString()} passages from ${st.sessions} sessions in ${st.projects} projects` +
      (st.waiting_bytes > 0 ? ` · indexing, ${(st.waiting_bytes / 1e6).toFixed(0)} MB to go` : "") : "Off: agents search only notes and chats here."));
  const tg = el("button", "toggle"); tg.type = "button"; tg.setAttribute("role", "switch"); tg.setAttribute("aria-checked", String(m.settings.sessions));
  tg.setAttribute("aria-label", "Search my coding sessions");
  tg.onclick = async () => { await api("/api/memory/settings", {method: "PUT", body: {sessions: !m.settings.sessions}}).catch(e => toast(e.message, true)); renderMemory(); };
  sw.append(words, tg);
  const search = el("form", "mem-search"); const q = inputEl({placeholder: "Search memory, e.g. how we fixed the SSE drops", autocomplete: "off"});
  const results = el("div", "list");
  search.append(q, btn("Search", "", null, "search")); search.lastChild.type = "submit";
  search.addEventListener("submit", async e => {
    e.preventDefault(); if (!q.value.trim()) return;
    results.replaceChildren(el("p", "sub", "Searching…"));
    try {
      const r = await api(`/api/memory/search?q=${encodeURIComponent(q.value.trim())}`);
      results.replaceChildren(...(r.hits.length ? r.hits.map(h => {
        const it = el("div", "hit"); const when = h.at ? new Date(h.at * 1000).toLocaleDateString([], {month: "short", day: "numeric"}) : "";
        it.append(el("span", "src", [{note: "note", chat: "chat", claude_code: "Claude Code", codex: "Codex"}[h.kind], h.project, h.kind !== "note" ? h.title : "", when].filter(Boolean).join(" · ")),
          el("span", "txt", h.text)); return it;
      }) : [el("p", "sub", "Nothing found.")]));
    } catch (err) { results.replaceChildren(el("p", "err", err.message)); }
  });
  const add = el("form", "note-add"); const text = inputEl({placeholder: "A note every agent should know, e.g. Deploys go out on Fridays", maxLength: 600});
  const scope = el("select"); scope.setAttribute("aria-label", "Which agents");
  scope.append(Object.assign(el("option", null, "All agents"), {value: "all"}), ...S.agents.map(a => Object.assign(el("option", null, `Only ${a.name}`), {value: a.id})));
  add.append(text, scope, btn("Add note", "primary", null, "plus")); add.lastChild.type = "submit";
  add.addEventListener("submit", async e => {
    e.preventDefault(); if (!text.value.trim()) return;
    try { await api("/api/memory/notes", {method: "POST", body: {text: text.value.trim(), scope: scope.value}}); renderMemory(); }
    catch (err) { toast(err.message, true); }
  });
  const notes = el("div", "list");
  for (const n of m.notes.slice().reverse()) {
    const it = el("div", "item"); const iic = el("span", "iic"); iic.append(ic("book"));
    const w = el("div"); w.append(el("b", null, n.text));
    const who = n.scope === "all" ? "all agents" : `only ${(S.agents.find(a => a.id === n.scope) || {}).name || n.scope}`;
    w.append(el("small", null, `${n.id} · ${who} · saved by ${n.by || "you"} · ${ago(n.at)}`));
    const ctl = el("div", "ctl"); ctl.append(btn("Forget", "ghost", async () => { await api(`/api/memory/notes/${n.id}`, {method: "DELETE"}).catch(() => {}); renderMemory(); }));
    it.append(iic, w, ctl); notes.append(it);
  }
  if (!m.notes.length) notes.append(el("p", "sub", "No notes yet. Agents add them when you tell them something worth keeping; you can add your own."));
  box.replaceChildren(intro, sw, el("p", "mem-stats", `${st.notes} notes · ${st.chats} chat turns searchable`), search, results,
    el("h3", "section-title", "Notes"), add, notes);
}

// ---- the side panel: files, terminal, browser ----------------------------------------------------------------
const SIDE = {pane: null};
function openPane(name) {
  if (!["files", "terminal", "browser"].includes(name)) return;
  $("side").hidden = false; SIDE.pane = name;
  for (const b of document.querySelectorAll("[data-pane]")) b.classList.toggle("on", b.dataset.pane === name);
  for (const p of ["files", "terminal", "browser"]) $(`pane-${p}`).hidden = p !== name;
  if (name === "files") loadTree();
  if (name === "terminal") { if (!TERMS.list.length) newTerminal(); else showTerm(TERMS.active || TERMS.list[0]); }
  if (name === "browser") { if (!BR.state.url || BR.state.url === "about:blank") browserEmpty(); liveConnect(); } else liveDisconnect();
}
function closePane() {
  $("side").hidden = true; SIDE.pane = null; setSideWide(false); liveDisconnect();
  for (const b of document.querySelectorAll("[data-pane]")) b.classList.remove("on");
}
function togglePane(name) { if (SIDE.pane === name) closePane(); else openPane(name); }
// Expanded, the panel takes the whole work area (a terminal or a page at full width); picking a view restores it.
function setSideWide(wide) {
  const b = $("sideWide"), words = wide ? "Restore the panel" : "Expand the panel";
  $("side").classList.toggle("wide", wide);
  b.setAttribute("aria-pressed", String(wide)); b.setAttribute("aria-label", words); b.title = words;
  b.querySelector(".ic").innerHTML = icon(wide ? "shrink" : "expand");
}
for (const b of document.querySelectorAll(".pane-btns [data-pane]")) b.onclick = () => togglePane(b.dataset.pane);
for (const b of document.querySelectorAll(".side-head [data-pane]")) b.onclick = () => openPane(b.dataset.pane);
$("sideClose").onclick = closePane;
$("sideWide").onclick = () => setSideWide(!$("side").classList.contains("wide"));
(() => {  // drag (or arrow keys on) the panel's left edge to resize it; the width is remembered on this laptop
  const side = $("side"), handle = $("resizer");
  const set = px => { const w = Math.round(Math.max(340, Math.min(px, window.innerWidth * 0.72))); side.style.setProperty("--side-w", `${w}px`); return w; };
  try { const w = localStorage.getItem("sa-side-w"); if (w) set(+w); } catch (e) { /* default width */ }
  const remember = () => { try { localStorage.setItem("sa-side-w", String(parseInt(side.style.getPropertyValue("--side-w")) || "")); } catch (e) { /* fine */ } };
  handle.addEventListener("pointerdown", e => {
    e.preventDefault(); handle.setPointerCapture(e.pointerId); handle.classList.add("drag");
    const right = side.getBoundingClientRect().right;
    const move = ev => set(right - ev.clientX);
    const up = () => { handle.classList.remove("drag"); handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", up); remember(); };
    handle.addEventListener("pointermove", move); handle.addEventListener("pointerup", up);
  });
  handle.addEventListener("keydown", e => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault(); set(side.getBoundingClientRect().width + (e.key === "ArrowLeft" ? 32 : -32)); remember();
  });
})();

// Files: the repos connected on This laptop, read only here (agents write through their tools).
const FILES = {current: null};
const LANGS = {py: "python", js: "javascript", mjs: "javascript", cjs: "javascript", jsx: "javascript", ts: "typescript", tsx: "typescript",
  json: "json", md: "markdown", markdown: "markdown", html: "xml", htm: "xml", xml: "xml", svg: "xml", css: "css", scss: "scss", less: "less",
  yml: "yaml", yaml: "yaml", toml: "ini", ini: "ini", cfg: "ini", sh: "bash", bash: "bash", zsh: "bash", ps1: "powershell", psm1: "powershell",
  go: "go", rs: "rust", java: "java", kt: "kotlin", rb: "ruby", php: "php", cs: "csharp", c: "c", h: "c", cpp: "cpp", cc: "cpp", hpp: "cpp",
  sql: "sql", swift: "swift", lua: "lua", r: "r", diff: "diff", patch: "diff", graphql: "graphql", vb: "vbnet"};
function langFor(name) {
  const lower = name.toLowerCase(); const ext = lower.includes(".") ? lower.split(".").pop() : lower;
  const lang = lower === "makefile" ? "makefile" : LANGS[ext];
  return lang && hljs.getLanguage(lang) ? lang : null;
}
async function loadTree() {
  const tree = $("tree");
  let roots;
  try { roots = (await api("/api/files/roots")).roots; } catch (e) { tree.replaceChildren(el("div", "note", e.message)); return; }
  tree.replaceChildren();
  if (!roots.length) {
    const n = el("div", "note", "Connect a repo on This laptop to browse its files here. ");
    const b = el("button", "link-btn", "Connect a repo"); b.type = "button"; b.onclick = () => go("laptop"); n.append(b);
    tree.append(n);
  }
  roots.forEach((r, i) => { const node = treeNode({name: r.name, path: r.name, dir: true}, true); tree.append(node); if (i === 0) node.querySelector("button").click(); });
  if (!FILES.current) viewerEmpty(roots.length);
}
function treeNode(entry, root) {
  const wrap = el("div", root ? "root" : null);
  const b = el("button"); b.type = "button"; b.title = entry.path;
  const caret = el("span", "ic caret"); if (entry.dir) caret.innerHTML = icon("caret");
  b.append(caret, ic(entry.dir ? "folder" : "file"), el("span", null, entry.name));
  wrap.append(b);
  if (!entry.dir) { b.onclick = () => openFile(entry.path, b); return wrap; }
  const kids = el("div", "kids"); kids.hidden = true; wrap.append(kids);
  b.setAttribute("aria-expanded", "false");
  b.onclick = async () => {
    const opening = kids.hidden;
    if (opening && !kids.childElementCount) {
      try { const r = await api(`/api/files/list?path=${encodeURIComponent(entry.path)}`); for (const e of r.entries) kids.append(treeNode(e)); if (!r.entries.length) kids.append(el("div", "note", "Empty")); }
      catch (e) { kids.append(el("div", "note", e.message)); }
    }
    kids.hidden = !opening; wrap.classList.toggle("open", opening); b.setAttribute("aria-expanded", String(opening));
  };
  return wrap;
}
function viewerEmpty(hasRoots) {
  const box = el("div", "viewer-empty"); box.append(agent("", currentAgent().color), el("b", null, hasRoots ? "Pick a file" : "No repos yet"),
    el("span", null, hasRoots ? "Files from your connected repos open here. Agents' edits show up as they happen." : "Files from your connected repos open here."));
  $("viewer").replaceChildren(el("div", "viewer-head"), box);
}
async function openFile(path, fromTree) {
  if (SIDE.pane !== "files") openPane("files");
  document.querySelectorAll("#tree button.on").forEach(x => x.classList.remove("on"));
  if (fromTree) fromTree.classList.add("on");
  FILES.current = path;
  const head = el("div", "viewer-head"); const label = el("span", "path", path); head.append(ic("file"), label);
  const body = el("div", "viewer-body");
  $("viewer").replaceChildren(head, body);
  let r;
  try { r = await api(`/api/files/read?path=${encodeURIComponent(path)}`); } catch (e) { body.append(el("div", "viewer-empty", e.message)); return; }
  label.textContent = r.path; label.title = r.path;
  const copy = el("button", "icon-btn small"); copy.type = "button"; copy.title = "Copy the path"; copy.setAttribute("aria-label", "Copy the path"); copy.append(ic("copy"));
  copy.onclick = () => navigator.clipboard.writeText(r.path).then(() => toast("Path copied."), () => toast(r.path));
  if (r.kind === "image") {
    head.append(copy);
    const box = el("div", "img"); const img = el("img"); img.alt = r.name; box.append(img); body.append(box);
    try { const res = await fetch(`/api/files/raw?path=${encodeURIComponent(path)}`, {headers: {"X-App-Key": KEY}}); img.src = URL.createObjectURL(await res.blob()); }
    catch (e) { box.replaceChildren(el("div", "viewer-empty", "Couldn't load the image.")); }
    return;
  }
  if (r.kind !== "text") { head.append(copy); body.append(el("div", "viewer-empty", r.kind === "large" ? `${r.name} is over 2 MB.` : `${r.name} isn't a text file.`)); return; }
  const code = () => body.replaceChildren(codeView(r.text, r.name));
  const preview = () => { const m = el("div", "md"); renderMd(m, r.text); body.replaceChildren(m); };
  if (/\.(md|markdown)$/i.test(r.name)) { head.append(segEl([["preview", "Preview"], ["source", "Source"]], "preview", k => (k === "preview" ? preview() : code())), copy); preview(); }
  else { head.append(copy); code(); }
}
function codeView(text, name) {
  const lines = text.split("\n"); if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  const src = lines.join("\n");
  const wrap = el("div", "code");
  const gutter = el("pre", "gutter", lines.map((_, i) => i + 1).join("\n"));
  const pre = el("pre"); const code = el("code", "hljs"); code.textContent = src;
  const lang = langFor(name);
  try {
    if (lang && src.length < 400_000) code.innerHTML = hljs.highlight(src, {language: lang, ignoreIllegals: true}).value;
    else if (!lang && src.length < 40_000) code.innerHTML = hljs.highlightAuto(src).value;
  } catch (e) { code.textContent = src; }
  pre.append(code); wrap.append(gutter, pre); return wrap;
}

// Terminal: a real shell on this laptop (PowerShell on Windows), in the first connected repo.
const TERMS = {list: [], active: null, n: 0};
function termTheme() {
  const css = getComputedStyle(document.documentElement); const v = n => css.getPropertyValue(n).trim();
  const dark = document.documentElement.dataset.theme !== "light";
  const ansi = dark
    ? ["#2A2830", "#F07A70", "#4CC38A", "#F2B32B", "#7FA6F0", "#B3A5F0", "#6CCFD0", "#D8D0C4", "#6F6960", "#FF9A90", "#7BE0AE", "#FFD166", "#A5C2FF", "#CFC3FF", "#9BE6E6", "#F3ECE0"]
    : ["#18171B", "#B23A31", "#2C7A4F", "#8F6400", "#2D60A3", "#6448B4", "#1F7676", "#8C857B", "#6B655D", "#A8443D", "#2C8A57", "#A87A00", "#3D74C2", "#7A5CCC", "#2A8C8C", "#18171B"];
  const names = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"];
  const theme = {background: v("--term-bg"), foreground: v("--text"), cursor: v("--brick"), cursorAccent: v("--term-bg"),
    selectionBackground: dark ? "rgba(217,103,92,.35)" : "rgba(168,68,61,.22)"};
  names.forEach((n, i) => { theme[n] = ansi[i]; theme[`bright${n[0].toUpperCase()}${n.slice(1)}`] = ansi[i + 8]; });
  return theme;
}
function newTerminal() {
  const id = ++TERMS.n;
  const box = el("div", "term"); $("terms").append(box);
  const term = new Terminal({fontFamily: '"JB Mono", "Cascadia Mono", Consolas, monospace', fontSize: 13, lineHeight: 1.15, cursorBlink: true,
    scrollback: 5000, theme: termTheme()});
  const fit = new FitAddon.FitAddon(); term.loadAddon(fit); term.open(box);
  const t = {id, name: `Terminal ${id}`, term, fit, box, ws: null, ended: false};
  TERMS.list.push(t);
  term.onData(d => {
    if (t.ended) { if (d === "\r") { t.ended = false; term.reset(); connectTerm(t); } return; }
    if (t.ws && t.ws.readyState === 1) t.ws.send(JSON.stringify({t: "in", d}));
  });
  term.onResize(({cols, rows}) => { if (t.ws && t.ws.readyState === 1) t.ws.send(JSON.stringify({t: "resize", c: cols, r: rows})); });
  new ResizeObserver(() => { if (box.offsetWidth && !box.hidden) { try { fit.fit(); } catch (e) { /* not laid out yet */ } } }).observe(box);
  showTerm(t); connectTerm(t);
}
function connectTerm(t) {
  try { t.fit.fit(); } catch (e) { /* default size */ }
  const q = new URLSearchParams({k: KEY, cols: t.term.cols, rows: t.term.rows});
  const ws = new WebSocket(`ws://${location.host}/api/terminal?${q}`);
  t.ws = ws;
  ws.onmessage = e => t.term.write(e.data);
  ws.onopen = () => { renderTermTabs(); if (TERMS.active === t) t.term.focus(); };
  ws.onclose = () => {
    if (t.ws !== ws) return;
    t.ended = true; renderTermTabs();
    t.term.write("\r\n\x1b[2m[the shell ended · press Enter to start a new one]\x1b[0m\r\n");
  };
}
function showTerm(t) {
  TERMS.active = t;
  for (const x of TERMS.list) x.box.hidden = x !== t;
  requestAnimationFrame(() => { try { t.fit.fit(); } catch (e) { /* hidden */ } t.term.focus(); });
  renderTermTabs();
}
function closeTerm(t) {
  const ws = t.ws; t.ws = null; if (ws) ws.close();
  t.term.dispose(); t.box.remove();
  TERMS.list = TERMS.list.filter(x => x !== t);
  if (TERMS.active === t) TERMS.active = TERMS.list[TERMS.list.length - 1] || null;
  if (TERMS.active) showTerm(TERMS.active); else { renderTermTabs(); closePane(); }
}
function renderTermTabs() {
  const bar = $("termTabs"); bar.replaceChildren();
  for (const t of TERMS.list) {
    const b = el("button", (t === TERMS.active ? "on" : "") + (t.ended ? " ended" : "")); b.type = "button";
    const x = el("span", "x"); x.setAttribute("role", "button"); x.setAttribute("aria-label", `Close ${t.name}`); x.append(ic("x"));
    x.onclick = ev => { ev.stopPropagation(); closeTerm(t); };
    b.append(el("i"), t.name, x); b.onclick = () => showTerm(t); bar.append(b);
  }
  const add = el("button", "add"); add.type = "button"; add.title = "New terminal"; add.setAttribute("aria-label", "New terminal"); add.append(ic("plus"));
  add.onclick = newTerminal; bar.append(add);
}

// Browser: the browser you share with your agents (a real Edge, run by this laptop), live: what an agent does shows here,
// and clicks, scrolling and typing here go to it. "Open in its own window" shows a page in a plain Super Agents window.
const BR = {ws: null, state: {}, frameUrl: null, sizeTimer: null, retry: null};
function normalizeUrl(raw) {
  let u = (raw || "").trim(); if (!u) return "";
  if (!/^https?:\/\//i.test(u)) u = (/^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(\/|$)/i.test(u) ? "http://" : "https://") + u;
  try {
    const x = new URL(u);  // never the app itself, under any loopback name
    return ["127.0.0.1", "localhost", "[::1]"].includes(x.hostname) && x.port === location.port ? "" : x.href;
  } catch (e) { return ""; }
}
async function openBrowser(raw) {
  const u = normalizeUrl(raw);
  if (!u) return toast("That address can't open here.", true);
  if (SIDE.pane !== "browser") openPane("browser");
  $("urlIn").value = u; liveNote("Opening…");
  try { await api("/api/browser/open", {method: "POST", body: {url: u}}); liveNote(""); } catch (e) { liveNote(e.message, true); }
}
function liveNote(text, bad) { const n = $("liveNote"); n.textContent = text || "You and your agents share this browser: click and type in it to use it yourself."; n.classList.toggle("bad", !!bad); }
function browserEmpty() {
  const e = $("frameEmpty");
  e.replaceChildren(agent("", currentAgent().color), el("b", null, "The browser you share with your agents"),
    el("span", "sub", "Preview your dev server or read docs; when an agent checks a page, you watch it here and can take over."));
  const row = el("div", "row gap");
  for (const port of [3000, 5173, 8000]) { const b = el("button", "chip-btn", `localhost:${port}`); b.type = "button"; b.onclick = () => openBrowser(`http://localhost:${port}`); row.append(b); }
  e.append(row); e.hidden = false; $("liveImg").hidden = true;
}
function liveSend(msg) { if (BR.ws && BR.ws.readyState === 1) BR.ws.send(JSON.stringify(msg)); }
function liveSize() {
  clearTimeout(BR.sizeTimer);
  BR.sizeTimer = setTimeout(() => { const b = $("live"); if (b.clientWidth) liveSend({type: "size", w: b.clientWidth, h: b.clientHeight}); }, 200);
}
function liveConnect() {
  if (BR.ws) return;
  clearTimeout(BR.retry);
  const ws = BR.ws = new WebSocket(`ws://${location.host}/api/browser/live?k=${encodeURIComponent(KEY)}`);
  ws.binaryType = "blob";
  liveNote("Starting the browser…");
  ws.onopen = () => { liveNote(""); liveSize(); };
  ws.onmessage = ev => {
    if (ev.data instanceof Blob) {
      const url = URL.createObjectURL(ev.data), img = $("liveImg");
      img.onload = () => { if (BR.frameUrl) URL.revokeObjectURL(BR.frameUrl); BR.frameUrl = url; };
      img.src = url;
      if (BR.state.url && BR.state.url !== "about:blank") { img.hidden = false; $("frameEmpty").hidden = true; }
      return;
    }
    const st = JSON.parse(ev.data);
    if (st.error) { liveNote(st.error, true); return; }
    BR.state = st;
    if (document.activeElement !== $("urlIn")) $("urlIn").value = st.url && st.url !== "about:blank" ? st.url : "";
    if (!st.url || st.url === "about:blank") browserEmpty();
    const badge = $("liveBadge"); badge.hidden = !st.driving; badge.textContent = st.driving ? `${st.driving} is using the browser` : "";
    const p = st.pointer, img = $("liveImg");
    if (p && Date.now() / 1000 - p[2] < 1.5 && img.naturalWidth) {
      const r = img.getBoundingClientRect(), box = $("live").getBoundingClientRect(), ring = $("liveRing");
      ring.style.left = `${r.left - box.left + p[0] * r.width / img.naturalWidth}px`; ring.style.top = `${r.top - box.top + p[1] * r.height / img.naturalHeight}px`;
      ring.hidden = false; ring.classList.remove("go"); void ring.offsetWidth; ring.classList.add("go");
    }
  };
  ws.onclose = () => { BR.ws = null; if (SIDE.pane === "browser") BR.retry = setTimeout(liveConnect, 2000); };
}
function liveDisconnect() { clearTimeout(BR.retry); if (BR.ws) { const ws = BR.ws; BR.ws = null; ws.onclose = null; ws.close(); } }
(() => {  // the person's own use of the shared browser: clicks, scrolling, typing and paste go through
  const live = $("live"), img = $("liveImg");
  const at = e => { const r = img.getBoundingClientRect(); return {x: Math.round((e.clientX - r.left) * img.naturalWidth / r.width), y: Math.round((e.clientY - r.top) * img.naturalHeight / r.height)}; };
  const on = () => !img.hidden && img.naturalWidth;
  live.addEventListener("click", e => { live.focus(); if (on() && e.target === img) liveSend({type: "click", ...at(e)}); });
  live.addEventListener("dblclick", e => { if (on() && e.target === img) liveSend({type: "click", ...at(e), count: 2}); });
  live.addEventListener("contextmenu", e => { if (on() && e.target === img) { e.preventDefault(); liveSend({type: "click", ...at(e), button: 2}); } });
  live.addEventListener("wheel", e => { if (on()) { e.preventDefault(); liveSend({type: "wheel", dx: e.deltaX, dy: e.deltaY}); } }, {passive: false});
  let movedAt = 0;
  live.addEventListener("mousemove", e => { if (on() && e.target === img && Date.now() - movedAt > 90) { movedAt = Date.now(); liveSend({type: "move", ...at(e)}); } });
  live.addEventListener("keydown", e => {
    if (!on() || (e.ctrlKey && e.key.toLowerCase() === "v")) return;  // paste comes as a paste event
    if (e.ctrlKey && (e.key === "`" || e.key.toLowerCase() === "b")) return;  // the app's own shortcuts
    e.preventDefault();
    if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) liveSend({type: "text", text: e.key});
    else if (!["Control", "Shift", "Alt", "Meta"].includes(e.key)) liveSend({type: "key", key: [e.ctrlKey && "Control", e.altKey && "Alt", e.metaKey && "Meta", e.shiftKey && e.key.length > 1 && "Shift", e.key === " " ? "Space" : e.key].filter(Boolean).join("+")});
  });
  live.addEventListener("paste", e => { const t = (e.clipboardData || {}).getData ? e.clipboardData.getData("text") : ""; if (on() && t) { e.preventDefault(); liveSend({type: "text", text: t}); } });
  new ResizeObserver(liveSize).observe(live);
})();
$("urlForm").addEventListener("submit", e => { e.preventDefault(); openBrowser($("urlIn").value); });
$("brBack").onclick = () => liveSend({type: "nav", to: "back"});
$("brReload").onclick = () => liveSend({type: "nav", to: "reload"});
const popOut = () => { const u = normalizeUrl($("urlIn").value); if (u) api("/api/browser/window", {method: "POST", body: {url: u}}).catch(e => toast(e.message, true)); };
$("brPop").onclick = popOut;

// ---- team: people and usage ------------------------------------------------------------------------------
let teamTab = "people";
function showTeamTab(tab) {
  teamTab = tab;
  for (const b of $("teamTabs").children) b.classList.toggle("on", b.dataset.tab === tab);
  for (const t of ["people", "sessions", "prompts", "files", "usage"]) $(`team-${t}`).hidden = t !== tab;
  const t = team(); $("teamSub").textContent = t ? `${t.name} · ${t.role === "lead" ? "you lead this team" : "member"}` : "";
  if (tab === "people") loadTeam();
  if (tab === "sessions") loadSessions();
  if (tab === "prompts") loadPrompts();
  if (tab === "files") loadShares();
  if (tab === "usage") loadUsage();
}

// ---- Super Team → Files: what teammates share with you, and what you share -------------------------------------
const fmtBytes = n => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`);
const SHARE_SEEN = new Set();
async function loadShares() {
  const box = $("team-files");
  let d;
  try { d = await hub(withTeam("shares")); } catch (e) { box.replaceChildren(el("p", "err", e.message)); return; }
  const head = el("div", "share-head");
  head.append(btn("Share files", "primary", openShareComposer, "plus"),
    el("p", "sub", "Specs, logs, screenshots: for one teammate or everyone, kept 14 days. They save them into their project's inbox, out of git. Code goes as a branch: ask Agent S to hand yours over."));
  const list = el("div", "list");
  for (const s of d.shares) { SHARE_SEEN.add(s.id); list.append(shareRow(s)); }
  if (!d.shares.length) list.append(el("p", "sub", "Nothing shared in the last 14 days."));
  box.replaceChildren(head, list);
}
function shareRow(s) {
  const it = el("div", "item share" + (s.status === "ready" ? "" : " off")), iic = el("span", "iic"), w = el("div"), ctl = el("div", "ctl");
  iic.append(ic(s.kind === "branch" ? "branch" : "file"));
  w.append(el("b", null, `${s.mine ? "You" : s.from.name} → ${s.to ? (s.for_me ? "you" : s.to.name) : "everyone"}`));
  if (s.kind === "branch") w.append(el("small", null, `Branch ${s.branch} of ${s.repo}`));
  else { const files = el("div", "share-files"); for (const f of s.files) files.append(el("span", "ck", `${f.name} · ${fmtBytes(f.size)}`)); w.append(files); }
  if (s.note) w.append(el("small", "share-note", s.note));
  const bits = [ago(s.created_at), s.status === "ready" ? `kept until ${new Date(s.expires_at * 1000).toLocaleDateString([], {month: "short", day: "numeric"})}` : s.status];
  if (s.saved_by.length) bits.push(`saved by ${s.saved_by.join(", ")}`);
  if (!s.can_get) bits.push("between two teammates: you see the record, not the files");
  w.append(el("small", null, bits.join(" · ")));
  if (s.status === "ready" && s.can_get && !s.mine) {
    const repos = ((S.laptop || {}).repos || []).filter(r => r.ok);
    if (s.kind === "branch") ctl.append(btn("Check it out", "primary", () => takeShare(s, "", ctl), "branch"));
    else if (!repos.length) ctl.append(el("small", null, "Connect a repo on This laptop to save them"));
    else {
      const pick = el("select"); pick.setAttribute("aria-label", "Save into which repo"); pick.hidden = repos.length < 2;
      for (const r of repos) pick.append(Object.assign(el("option", null, r.name), {value: r.name}));
      const saved = s.saved_by.includes((S.user || {}).name);
      if (saved) ctl.append(el("span", "ck ok", "saved ✓"));
      ctl.append(pick, btn(saved ? "Save again" : repos.length > 1 ? "Save" : `Save to ${repos[0].name}`, saved ? "ghost" : "primary", () => takeShare(s, pick.value, ctl), "plus"));
    }
  }
  if (s.status !== "deleted" && (s.mine || (team() || {}).role === "lead")) ctl.append(btn("Delete", "ghost", async () => {
    try { await hub(withTeam(`shares/${s.id}`), {method: "DELETE"}); } catch (e) { toast(e.message, true); }
    loadShares();
  }));
  it.append(iic, w, ctl);
  return it;
}
async function takeShare(s, repo, ctl) {
  ctl.querySelectorAll("button, select").forEach(b => { b.disabled = true; });
  try {
    const r = await api(`/api/shares/${s.id}/take`, {method: "POST", body: {team: S.team, repo}});
    if (r.branch) toast(`${r.repo} is on ${r.branch} now.`);
    else { toast(`Saved into ${r.repo}'s inbox: ${r.saved.map(p => p.split("/").pop()).join(", ")}.`); openPane("files"); openFile(r.saved[0]); }
  } catch (e) { toast(e.message, true); }
  loadShares();
}
const b64 = buf => { const b = new Uint8Array(buf); let s = ""; for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000)); return btoa(s); };
function openShareComposer() {
  const files = inputEl({type: "file", multiple: true}); files.setAttribute("aria-label", "Files to share");
  const to = el("select"); to.append(Object.assign(el("option", null, "Everyone in the team"), {value: ""}));
  for (const m of ((S.board || {}).members || []).filter(m => m.name !== (S.user || {}).name)) to.append(Object.assign(el("option", null, m.name), {value: m.name}));
  const note = textareaEl({placeholder: "A note: what it is, what to do with it", maxLength: 1000, rows: 3});
  const send = btn("Share", "primary", async () => {
    const picked = [...files.files];
    if (!picked.length) return toast("Pick a file to share.", true);
    const big = picked.find(f => f.size > 25 * 1048576); if (big) return toast(`${big.name} is over 25 MB.`, true);
    send.disabled = true; send.textContent = "Sharing…";
    try {
      const body = {team: S.team, to: to.value, note: note.value.trim(), files: await Promise.all(picked.map(async f => ({name: f.name, data: b64(await f.arrayBuffer())})))};
      const s = await api("/api/shares/send", {method: "POST", body});
      toast(`Shared with ${s.to ? s.to.name : "everyone"}: they have it for 14 days.`); closeDrawer(); if (teamTab === "files") loadShares();
    } catch (e) { toast(e.message, true); send.disabled = false; send.textContent = "Share"; }
  }, "send");
  openDrawer("Super Team · Files", "Share files", [groupBox("Files (up to 10, 25 MB each)", files), groupBox("With", to), groupBox("Note", note),
    el("p", "sub", "They leave this laptop: they're uploaded to your team's private storage and kept 14 days. Files that look like secrets (.env, keys, text with a token in it) are refused.")], [send]);
}
for (const b of $("teamTabs").children) b.onclick = () => showTeamTab(b.dataset.tab);

// The usage counter: what the team's AI uses. Coding agents' tokens are counted on each laptop from the agent's own
// log (numbers only); Super Agents counts its Nemotron calls. "Tokens" = fresh input + cache writes + output.
const fmtTok = n => (n = n || 0) >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M`
  : n >= 1e4 ? `${Math.round(n / 1e3)}k` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n);
const TZ = -new Date().getTimezoneOffset();
const USAGE = {days: 7, data: null};
const SERIES = [["claude_code", "Claude Code", "--u-claude"], ["codex", "Codex", "--u-codex"], ["agents", "Super Agents", "--u-agents"]];
async function loadUsageChip() {
  if (!S.team) return;
  try {
    const u = await hub(withTeam(`usage?days=1&tz=${TZ}`));
    const c = $("usageChip"); c.hidden = false; c.replaceChildren(ic("gauge"), `${fmtTok(u.total)} tokens today`);
    c.title = `AI usage today · coding agents ${fmtTok(u.coding.tokens)} · Super Agents ${fmtTok(u.agents.tokens)}`;
  } catch (e) { /* next poll */ }
}
async function loadUsage() {
  const box = $("team-usage");
  if (!USAGE.data) box.replaceChildren(el("div", "skeleton"));
  try { USAGE.data = await hub(withTeam(`usage?days=${USAGE.days}&tz=${TZ}`)); }
  catch (e) { box.replaceChildren(el("p", "err", e.message)); return; }
  renderUsage();
}
function figure(label, value, small, color, dim) {
  const f = el("div", "figure" + (dim ? " dim" : "")); const l = el("div", "label"); const i = el("i");
  if (color) i.style.setProperty("--c", `var(${color})`); l.append(i, label);
  f.append(l, el("b", null, fmtTok(value)), el("span", null, small)); return f;
}
function usageChart(days) {
  // drawn at the width it's shown at, so the axis text stays at its CSS size
  const W = Math.max(480, ($("team-usage").clientWidth || 760) - 34), H = 168, top = 10, bottom = 22, left = 44, n = days.length;
  const total = d => d.claude_code + d.codex + d.agents;
  const max = Math.max(1, ...days.map(total));
  const y = v => H - bottom - (v / max) * (H - top - bottom);
  const slot = (W - left) / n, bw = Math.max(3, Math.min(34, slot * 0.62));
  const s = svg("svg", {viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "AI tokens per day"});
  for (const g of [0, 0.5, 1]) {
    s.append(svg("line", {x1: left, x2: W, y1: y(max * g), y2: y(max * g), class: "grid"}));
    const t = svg("text", {x: left - 8, y: y(max * g) + 4, "text-anchor": "end"}); t.textContent = fmtTok(Math.round(max * g)); s.append(t);
  }
  days.forEach((d, i) => {
    const g = svg("g", {}); const x = left + i * slot + (slot - bw) / 2; let base = 0;
    for (const [key, , color] of SERIES) {
      if (!d[key]) continue;
      g.append(svg("rect", {x, y: y(base + d[key]), width: bw, height: Math.max(1, y(base) - y(base + d[key])), rx: 2, fill: `var(${color})`}));
      base += d[key];
    }
    const tip = svg("title", {}); tip.textContent = `${d.day} · ${SERIES.map(([k, label]) => `${label} ${fmtTok(d[k])}`).join(" · ")}`; g.append(tip);
    if (n <= 10 || i % 5 === n % 5 || i === n - 1) { const t = svg("text", {x: x + bw / 2, y: H - 6, "text-anchor": "middle"}); t.textContent = d.day.slice(8); g.append(t); }
    s.append(g);
  });
  const box = el("div", "usage-chart"); const legend = el("div", "legend-row");
  for (const [, label, color] of SERIES) { const span = el("span"); const i = el("i"); i.style.setProperty("--c", `var(${color})`); span.append(i, label); legend.append(span); }
  box.append(s, legend); return box;
}
function table(head, rows) {
  const t = el("table", "ut"); const tr = el("tr");
  for (const [label, num] of head) tr.append(el("th", num ? "num" : null, label));
  const thead = el("thead"); thead.append(tr); const tbody = el("tbody");
  for (const r of rows) tbody.append(r);
  t.append(thead, tbody); return t;
}
function renderUsage() {
  const u = USAGE.data; const box = $("team-usage");
  const bar = el("div", "usage-bar");
  bar.append(segEl([[1, "Today"], [7, "7 days"], [30, "30 days"]], USAGE.days, d => { USAGE.days = d; loadUsage(); }),
    el("span", "sub", u.scope === "team" ? "You lead this team, so you see everyone's numbers." : "You see the team's totals and your own numbers; the lead sees everyone's."));
  const tiles = el("div", "usage-top");
  tiles.append(figure("Coding agents", u.coding.tokens, `${u.coding.turns} turns · ${u.coding.sessions} sessions · Claude Code ${fmtTok(u.tools.claude_code.tokens)}, Codex ${fmtTok(u.tools.codex.tokens)}`, "--u-claude"),
    figure("Super Agents", u.agents.tokens, `${u.agents.calls} Nemotron calls`, "--u-agents"),
    figure("Cache reads", u.coding.cr, "Context the agents re-read each call. Not in the totals.", null, true));
  const nodes = [bar, tiles];
  if (u.days > 1) nodes.push(usageChart(u.by_day));
  const titles = Object.fromEntries((S.board ? S.board.tasks : []).map(t => [t.task, t.title]));
  const taskRows = u.tasks.map(t => {
    const tr = el("tr"); const cell = el("td", "t"); const b = el("button", "tchip", t.task); b.type = "button"; b.onclick = () => openTask(t.task);
    cell.append(b, " ", titles[t.task] || ""); cell.append(el("small", null, t.people.join(", ")));
    tr.append(cell, el("td", "num", fmtTok(t.tokens)), el("td", "num", String(t.turns))); return tr;
  });
  const peopleRows = u.people.map(p => {
    const tr = el("tr"); const name = el("td", "t", p.name); if (p.you) name.append(el("span", "you", "you"));
    tr.append(name, el("td", "num", fmtTok(p.coding.tokens)), el("td", "num", fmtTok(p.agents.tokens)), el("td", "num", String(p.sessions))); return tr;
  });
  const left = el("section", "panel"); left.append(el("h3", null, "By task"),
    taskRows.length ? table([["Task"], ["Tokens", 1], ["Turns", 1]], taskRows) : el("p", "sub", "No task has AI usage in this range yet."));
  const right = el("section", "panel"); right.append(el("h3", null, u.scope === "team" ? "By person" : "You"),
    peopleRows.length ? table([["Name"], ["Coding", 1], ["Agents", 1], ["Sessions", 1]], peopleRows) : el("p", "sub", "Nothing in this range yet."));
  const cols = el("div", "usage-cols"); cols.append(left, right); nodes.push(cols);
  if (u.models.length) { const m = el("div", "models"); for (const x of u.models) m.append(el("span", "tag", `${x.model} · ${fmtTok(x.tokens)}`)); nodes.push(m); }
  if (u.prompted && u.prompted.length) {
    const rows = u.prompted.map(x => { const tr = el("tr"); tr.append(el("td", "t", `${x.from} → ${x.to}'s sessions`), el("td", "num", String(x.prompts)), el("td", "num", fmtTok(x.tokens))); return tr; });
    const sec = el("section", "panel"); sec.style.marginBottom = "14px";
    sec.append(el("h3", null, "Prompts into teammates' sessions"), table([["Who"], ["Prompts", 1], ["Tokens", 1]], rows)); nodes.push(sec);
  }
  if (!u.total) nodes.splice(2, 0, el("div", "empty", "No AI usage in this range yet. Each teammate's next Claude Code or Codex turn shows up here once their Super Agents is up to date."));
  nodes.push(el("p", "sub small", "Tokens = fresh input + cache writes + output. Coding agents' tokens are counted on each laptop from the agent's own log; only the numbers leave it. Kept 30 days."));
  box.replaceChildren(...nodes);
}

// Super Team: prompts into teammates' coding sessions, by each owner's rules, all on record.
const TOOL_LABEL = {claude_code: "Claude Code", codex: "Codex"};
const P_STATUS = {pending: "waiting", approved: "allowed", running: "running", done: "answered", failed: "failed",
  denied: "denied", cancelled: "cancelled", stopped: "stopped", expired: "expired"};
const INBOX = new Set();
let promptBox = "all", promptTimer = null;
async function checkInbox() {
  if (!S.team) return;
  try {
    const r = await hub(withTeam("prompts?box=in&limit=30"));
    const waiting = r.prompts.filter(p => p.yours_to_decide);
    const b = $("promptBadge"); b.hidden = !waiting.length; b.textContent = String(waiting.length);
    const fresh = waiting.filter(p => !INBOX.has(p.id)); fresh.forEach(p => INBOX.add(p.id));
    if (fresh.length) toast(fresh.length === 1 ? `${fresh[0].from.name} wants to prompt your ${TOOL_LABEL[fresh[0].tool]} session. Super Team → Prompts.`
      : `${fresh.length} prompts are waiting for you. Super Team → Prompts.`);
    const first = !checkInbox.sharesRead;  // what was already there when the app opened isn't news
    const shared = (await hub(withTeam("shares"))).shares.filter(s => s.for_me && s.status === "ready");
    checkInbox.sharesRead = true;
    const news = shared.filter(s => !SHARE_SEEN.has(s.id)); news.forEach(s => SHARE_SEEN.add(s.id));
    if (news.length && !first) toast(news.length === 1 ? `${news[0].from.name} shared ${news[0].kind === "branch" ? `branch ${news[0].branch}` : `${news[0].files.length} file${news[0].files.length === 1 ? "" : "s"}`} with you. Super Team → Files.`
      : `${news.length} new shares for you. Super Team → Files.`);
  } catch (e) { /* next poll */ }
}
async function loadSessions() {
  const box = $("team-sessions");
  let d;
  try { d = await hub(withTeam("sessions")); } catch (e) { box.replaceChildren(el("p", "err", e.message)); return; }
  const theirs = d.sessions.filter(x => !x.mine);
  const sec = el("section"); sec.append(el("h3", "section-title", "Teammates' sessions"));
  if (theirs.length) { const rows = el("div", "list"); for (const x of theirs) rows.append(sessionRow(x)); sec.append(rows); }
  else sec.append(el("p", "sub", "No teammate has a Claude Code or Codex session from the last day. They show up here as teammates work."));
  box.replaceChildren(rulesCard(d.me), sec);
}
function rulesCard(me) {
  const card = el("section", "panel rules"); const draft = {...me};
  const save = async () => {
    try {
      await hub(withTeam("sessions/access"), {method: "PUT", body: draft});
      if (Date.now() - (rulesCard.saidAt || 0) > 4000) { rulesCard.saidAt = Date.now(); toast("Saved your rules for teammates' prompts."); }
    } catch (e) { toast(e.message, true); }
  };
  const limit = inputEl({type: "number", min: 1000, step: 1000, value: me.daily_tokens || 200000, className: "mono"});
  limit.hidden = !me.daily_tokens; limit.setAttribute("aria-label", "Tokens per teammate per day");
  limit.onchange = () => { draft.daily_tokens = Math.max(1000, Math.round(+limit.value || 1000)); save(); };
  const limits = el("div", "row gap");
  limits.append(segEl([["none", "Unlimited"], ["limit", "Set a limit"]], me.daily_tokens ? "limit" : "none", k => {
    limit.hidden = k !== "limit"; draft.daily_tokens = k === "limit" ? Math.max(1000, Math.round(+limit.value || 200000)) : null; save();
  }), limit);
  card.append(el("h3", null, "Your sessions"),
    el("p", "sub", "Teammates and your lead can send prompts into your Claude Code and Codex sessions. They run on this laptop while Super Agents is open, as a copy of the session, so the session you're in isn't touched. Claude Code runs them restricted: no commands, and files only in that repo. Every prompt is on the team's record."),
    groupBox("Prompts from teammates", segEl([["off", "Off"], ["ask", "Ask me each time"], ["auto", "Run automatically"]], me.mode, k => { draft.mode = k; save(); })),
    groupBox("They can", segEl([["read", "Read and answer"], ["edit", "Also edit files"]], me.access, k => { draft.access = k; save(); })),
    groupBox("Tokens per teammate per day", limits));
  return card;
}
function sessionRow(x) {
  const it = el("div", "item sess" + (x.mode === "off" ? " off" : ""));
  const face = el("span", "iic"); face.append(mascot(x.owner.name, x.active ? "idle" : "sleep"));
  const w = el("div"); const head = el("b", null, `${x.owner.name} · ${TOOL_LABEL[x.tool] || x.tool}`);
  if (x.active) head.append(el("span", "pill-tag on", "active"));
  const where = [x.repo, x.branch, x.task].filter(Boolean).join(" · ") || "a repo";
  const rules = x.mode === "off" ? `${x.owner.name} isn't taking prompts`
    : `${x.mode === "ask" ? `Asks ${x.owner.name} first` : "Runs automatically"} · ${x.access === "read" ? "read only" : "can edit"}`
      + (x.daily_tokens ? ` · you've used ${fmtTok(x.used_today)} of ${fmtTok(x.daily_tokens)} today` : "")
      + (x.app_online ? "" : ` · ${x.owner.name}'s Super Agents is ${x.app_seen ? `offline since ${ago(x.app_seen)}` : "closed"}: prompts wait for it`);
  const thread = x.thread ? ` · ${x.thread} prompt${x.thread === 1 ? "" : "s"} in the thread` : "";
  w.append(head, el("small", null, `${where} · ${x.turns} turn${x.turns === 1 ? "" : "s"} · ${x.active ? "now" : ago(x.last)}${thread}`), el("small", null, rules));
  const send = btn(x.thread ? "Open thread" : "Prompt", "", () => openThread(x.session), "send"); send.disabled = x.mode === "off" && !x.thread;
  const ctl = el("div", "ctl"); ctl.append(send); it.append(face, w, ctl); return it;
}
// A session's Super Team thread: saved on the hub, so it reads the same while the owner's laptop is closed; prompts sent
// then wait and run when it's back, and each follow-up is answered with the thread so far.
let threadTimer = null;
async function openThread(session) {
  let t;
  try { t = await hub(withTeam(`sessions/${encodeURIComponent(session)}/thread`)); } catch (e) { return toast(e.message, true); }
  const x = t.session, owner = x.owner.name;
  const head = el("p", "thread-head");
  head.append(el("b", null, `${owner}'s ${TOOL_LABEL[x.tool] || x.tool} session`), ` · ${[x.repo, x.branch, x.task].filter(Boolean).join(" · ") || "a repo"} · `,
    x.app_online ? `${owner}'s Super Agents is open` : `${owner}'s Super Agents is ${x.app_seen ? `offline since ${ago(x.app_seen)}` : "closed"}: what you send waits and runs when it's back`);
  const rules = x.mode === "off" ? `${owner} isn't taking prompts now` : `${x.mode === "ask" ? `${owner} allows each prompt` : "Runs by their rules"} · ${x.access === "read" ? "read only" : "can edit"}`;
  const list = el("div", "thread");
  for (const p of t.prompts) {
    const q = el("div", "turn-q", p.prompt); q.append(el("small", null, `${p.yours ? "you" : p.from.name} · ${ago(p.created_at)}`));
    const a = el("div", "turn-a");
    if (p.result) { const md = el("div", "md"); renderMd(md, p.result); a.append(md); }
    else a.append(el("span", "wait", p.status === "approved" && !x.app_online ? `queued: runs when ${owner}'s Super Agents is back`
      : {pending: `waiting for ${owner} to allow it`, approved: "allowed, starting", running: "running…", denied: `${owner} denied it`,
         cancelled: "cancelled", expired: "expired: it didn't run within a week", failed: "failed"}[p.status] || p.status));
    a.append(el("span", "meta", [P_STATUS[p.status] || p.status, p.tokens ? `${fmtTok(p.tokens)} tokens` : ""].filter(Boolean).join(" · ")));
    list.append(q, a);
  }
  if (!t.prompts.length) list.append(el("p", "sub", `Nothing yet. Ask ${owner}'s session something: it answers with everything that session knows.`));
  const ta = textareaEl({rows: 2, maxLength: 4000, placeholder: t.prompts.length ? "Follow up…" : `Ask ${owner}'s session… e.g. What's left on ${x.task || "this task"}?`});
  const send = btn("Send", "primary", async () => {
    if (!ta.value.trim()) return; send.disabled = true;
    try { await hub(withTeam("prompts"), {method: "POST", body: {session, prompt: ta.value.trim()}}); openThread(session); }
    catch (e) { toast(e.message, true); send.disabled = false; }
  }, "send");
  ta.addEventListener("keydown", e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send.click(); } });
  const canSend = x.mode !== "off" && !x.mine;
  openDrawer(`Super Team · ${rules}`, x.task ? `${owner} · ${x.task}` : `${owner}'s session`, [head, list], canSend ? [ta, send] : []);
  $("dFoot").classList.add("compose");
  $("dBody").scrollTop = $("dBody").scrollHeight;
  if (canSend) ta.focus();
  clearTimeout(threadTimer);
  if (t.prompts.some(p => ["pending", "approved", "running"].includes(p.status)))
    threadTimer = setTimeout(() => { if (!$("drawer").hidden && $("dTitle").textContent.startsWith(owner)) openThread(session); }, 5000);
}
async function loadPrompts() {
  const box = $("team-prompts");
  let r;
  try { r = await hub(withTeam(`prompts?box=${promptBox}&limit=80`)); } catch (e) { box.replaceChildren(el("p", "err", e.message)); return; }
  const lead = r.role === "lead";
  const bar = el("div", "usage-bar");
  bar.append(segEl([["all", lead ? "Whole team" : "Everything of yours"], ["out", "Sent"], ["in", "Received"]], promptBox, k => { promptBox = k; loadPrompts(); }),
    el("span", "sub", `Every prompt into a teammate's session is on record: who asked what, who allowed it, what it used.${lead ? " As the lead, you see the whole team's." : " The lead sees the whole team's."}`));
  const waiting = r.prompts.filter(p => p.yours_to_decide), rest = r.prompts.filter(p => !p.yours_to_decide);
  const nodes = [bar];
  if (waiting.length) { const w = el("div", "list"); waiting.forEach(p => w.append(promptCard(p, true))); nodes.push(el("h3", "section-title", "Waiting for you"), w); }
  const list = el("div", "list"); rest.forEach(p => list.append(promptCard(p, false)));
  nodes.push(el("h3", "section-title", "Record"), rest.length ? list : el("p", "sub", "No prompts yet. Send one from Sessions."));
  box.replaceChildren(...nodes);
  clearTimeout(promptTimer);
  if (r.prompts.some(p => p.status === "approved" || p.status === "running"))
    promptTimer = setTimeout(() => { if (S.view === "team" && teamTab === "prompts") loadPrompts(); }, 4000);
  checkInbox();
}
function promptCard(p, decide) {
  const c = el("article", `pcard ${p.status}`);
  const head = el("div", "phead");
  head.append(el("b", null, `${p.from.name} → ${p.to.name}'s ${TOOL_LABEL[p.tool] || p.tool}`), el("span", "sub small", [p.task, p.repo].filter(Boolean).join(" · ")),
    el("span", "grow"), el("span", "pstatus", P_STATUS[p.status] || p.status));
  const meta = el("div", "pmeta");
  meta.append(el("span", null, ago(p.created_at)), el("span", null, p.access === "read" ? "read only" : "can edit"));
  if (p.decided_by) meta.append(el("span", null, p.decided_by === "auto" ? "ran by their rules" : p.status === "denied" ? `${p.to.name} denied it` : `${p.to.name} allowed it`));
  if (p.tokens) meta.append(el("span", null, `${fmtTok(p.tokens)} tokens`));
  c.append(head, el("blockquote", "pprompt", p.prompt), meta);
  if (p.result) { const ans = el("div", "answer md pans"); renderMd(ans, p.result); c.append(ans); }
  if (decide) {
    const row = el("div", "row gap");
    row.append(el("span", "sub small", p.access === "read" ? "It can read this repo and answer. It can't change anything or run commands."
      : "It can read and edit files in this repo. It can't run commands."), el("span", "grow"),
      btn("Deny", "ghost", () => decidePrompt(p, false)), btn("Allow and run", "primary", () => decidePrompt(p, true), "play"));
    c.append(row);
  } else if (p.yours && (p.status === "pending" || p.status === "approved")) {
    const row = el("div", "row gap"); row.append(el("span", "grow"), btn("Cancel", "ghost", async () => {
      try { await hub(withTeam(`prompts/${p.id}/cancel`), {method: "POST", body: {}}); loadPrompts(); } catch (e) { toast(e.message, true); }
    }));
    c.append(row);
  }
  return c;
}
async function decidePrompt(p, ok) {
  try {
    await hub(withTeam(`prompts/${p.id}/decide`), {method: "POST", body: {approve: ok}});
    if (ok) api("/api/superteam/poke", {method: "POST"}).catch(() => {});
    toast(ok ? "Allowed. It runs on this laptop now." : "Denied."); loadPrompts();
  } catch (e) { toast(e.message, true); }
}

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

  const proj = el("section", "panel"), plist = el("ul", "repos");
  proj.append(el("h3", null, "Team projects"), el("p", "sub", "Your team's GitHub repos. Get one and it's cloned into a folder you pick, with your own GitHub sign-in, then connected here. Agents commit and push there like Claude Code: on a branch, asking before each push."), plist);
  left.append(proj);
  fillProjects(proj, plist);

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
  nv.append(el("p", "sub", "Except what you allow: a prompt a teammate sends into one of your sessions, and its answer, go on the team's record (Super Team → Sessions sets your rules)."));
  nv.append(el("p", "sub", "What goes: a one-line summary per turn, written on this laptop, plus facts such as files changed, tests passed or failed, and token counts."),
    el("p", "sub", "Chats with your agents in this app are different: to answer, each message and what its tools read go to Nemotron through the Super Agents server. They aren't stored there; chats are kept on this laptop."));
  never.append(nv); right.append(never);
  grid.append(left, right);
}

const HELPERS = {manager: "Git Credential Manager", "manager-core": "Git Credential Manager", wincred: "the Windows credential store"};
const sameRepo = u => (u || "").trim().replace(/^git@github\.com:/, "https://github.com/").replace(/\.git$|\/$/g, "").toLowerCase();
async function fillProjects(panel, ul) {
  let r, g;
  try { [r, g] = await Promise.all([hub(`teams/${S.team}/repos`), api("/api/laptop/git")]); }
  catch (e) { ul.replaceChildren(el("li", "sub", e.message)); return; }
  const here = new Set(Object.values(g.origins || {}).map(sameRepo));
  ul.replaceChildren();
  for (const p of r.repos) {
    const li = el("li", "repo"), f = el("span", "folder"), ctl = el("div", "checks"); f.append(ic("github"));
    if (here.has(sameRepo(p.url))) ctl.append(el("span", "ck ok", "on this laptop ✓"));
    else {
      const get = btn("Get the project", "primary", async () => {
        get.disabled = true; get.textContent = "Pick where to put it…";
        try {
          const res = await api("/api/laptop/clone", {method: "POST", body: {url: p.url}});
          if (!res.cancelled) { toast(res.ok ? `${p.name} is in ${res.path} and connected.` : `Cloned into ${res.path}, but connecting it failed.`, !res.ok); await refreshLaptop(false); }
        } catch (e) { toast(e.message, true); }
        if (S.view === "laptop") renderLaptop();
      }, "plus");
      ctl.append(get);
    }
    if (r.can_edit) ctl.append(btn("Remove", "ghost", async () => {
      try { await hub(`teams/${S.team}/repos?url=${encodeURIComponent(p.url)}`, {method: "DELETE"}); } catch (e) { toast(e.message, true); }
      renderLaptop();
    }));
    li.append(f, el("b", null, p.name), ctl); ul.append(li);
  }
  if (!r.repos.length) ul.append(el("li", "sub", r.can_edit ? "No repos linked yet. Link your team's GitHub repos and teammates get them in one click." : "Your lead hasn't linked the team's GitHub repos yet."));
  if (r.can_edit) {
    const form = el("form", "row gap"), url = inputEl({placeholder: "https://github.com/owner/repo", autocomplete: "off", spellcheck: false});
    url.setAttribute("aria-label", "A GitHub repo for the team"); url.style.flex = "1";
    form.append(url, btn("Link repo", "", null, "plus")); form.lastChild.type = "submit";
    form.addEventListener("submit", async ev => {
      ev.preventDefault(); if (!url.value.trim()) return;
      try { await hub(`teams/${S.team}/repos`, {method: "POST", body: {url: url.value.trim()}}); renderLaptop(); } catch (e) { toast(e.message, true); }
    });
    panel.append(form);
  }
  const helper = HELPERS[g.helper] || (g.helper ? g.helper : "");
  panel.append(el("p", "sub", !g.git ? "Git isn't installed here: install Git for Windows (it brings Git Credential Manager for GitHub sign-in)."
    : `Git ✓ · GitHub sign-in through ${helper || "no credential helper: pushes will fail until you set one up (Git for Windows includes Git Credential Manager)"}`
      + ` · ${g.gh ? "GitHub CLI ✓: when it's signed in, pull requests open directly" : "no GitHub CLI: pull requests open on github.com for you to click Create"}.`));
}

// ---- settings: the account, the look, and what you share (the same switches as This laptop, Agents → Memory and
// Super Team → Sessions, in one place) -------------------------------------------------------------------------
function switchEl(title, sub, on, label, onToggle) {
  const s = el("div", "switch"), words = el("div"); words.append(el("b", null, title), el("small", null, sub));
  const tg = el("button", "toggle"); tg.type = "button"; tg.setAttribute("role", "switch"); tg.setAttribute("aria-checked", String(on));
  tg.setAttribute("aria-label", label); tg.onclick = onToggle;
  s.append(words, tg); return s;
}
const SHORTCUTS = [["New chat", "Ctrl N"], ["Collapse or expand the sidebar", "Ctrl B"], ["Settings", "Ctrl ,"], ["Terminal", "Ctrl `"],
  ["Switch mode: Manual, Auto, Plan (in the message box)", "Shift Tab"], ["Send · new line", "Enter · Shift Enter"],
  ["Send a follow-up in a Super Team thread", "Ctrl Enter"], ["Close a menu or drawer", "Esc"]];
function renderSettings() {
  const box = $("settingsBody"), u = S.user || {}, t = team(), L = S.laptop || {};
  const acct = el("section", "panel"), who = el("div", "acct"), av = $("meAvatar").cloneNode(true); av.removeAttribute("id");
  const words = el("div"); words.append(el("b", null, u.name || ""), el("small", null, u.email || ""));
  if (t) words.append(el("small", null, `${t.role === "lead" ? "Lead" : "Member"} of ${t.name}`));
  who.append(av, words, btn("Sign out", "", () => $("signOutBtn").click(), "out"));
  acct.append(el("h3", null, "Account"), who);

  const look = el("section", "panel");
  const theme = segEl([["dark", "Dark"], ["light", "Light"]], document.documentElement.dataset.theme, k => setTheme(k)); theme.classList.add("theme-seg");
  look.append(el("h3", null, "Appearance"), groupBox("Theme", theme, "The sidebar folds to icons with its button at the top, or Ctrl+B."));

  const share = el("section", "panel"); share.append(el("h3", null, "Privacy"));
  if (L.team) share.append(switchEl("Share my coding sessions with the team", L.paused ? "Paused: hooks record nothing until you turn it back on." : "A one-line summary per turn and facts like files changed and tests run. Never prompts, code or tool output.",
    !L.paused, "Share my coding sessions", async () => {
      try { S.laptop = await api("/api/laptop/pause", {method: "POST", body: {paused: !L.paused}}); renderLaptopChip(); } catch (e) { toast(e.message, true); }
      renderSettings();
    }));
  else share.append(el("p", "sub", "This laptop isn't connected to a team, so it shares nothing. Connect it on This laptop."));
  api("/api/memory").then(m => share.append(switchEl("Let agents search my Claude Code and Codex sessions",
    m.settings.sessions ? "Your prompts and the agents' replies, in every project on this laptop. The index stays here." : "Off: agents search only notes and chats.",
    m.settings.sessions, "Search my coding sessions", async () => {
      await api("/api/memory/settings", {method: "PUT", body: {sessions: !m.settings.sessions}}).catch(e => toast(e.message, true));
      renderSettings();
    }))).catch(() => {});
  api("/api/browser/state").then(b => {
    if (!b.sites.length) return;
    const list = el("div", "row gap"); list.style.flexWrap = "wrap";
    for (const s of b.sites) list.append(btn(`${s} ✕`, "ghost", async () => { await api("/api/browser/sites", {method: "POST", body: {site: s, allowed: false}}).catch(e => toast(e.message, true)); renderSettings(); }));
    share.append(groupBox("Sites agents use in the browser without asking (localhost always)", list));
  }).catch(() => {});
  api("/api/desktop/state").then(d => {
    if (!d.apps.length) return;
    const list = el("div", "row gap"); list.style.flexWrap = "wrap";
    for (const a of d.apps) list.append(btn(`${a} ✕`, "ghost", async () => { await api("/api/desktop/apps", {method: "POST", body: {site: a, allowed: false}}).catch(e => toast(e.message, true)); renderSettings(); }));
    share.append(groupBox("Apps agents use without asking (Desktop)", list));
  }).catch(() => {});

  const keys = el("section", "panel"), dl = el("dl", "keys");
  for (const [what, combo] of SHORTCUTS) {
    const dd = el("dd"); combo.split(" · ").forEach((c, i) => { if (i) dd.append(" · "); dd.append(el("kbd", null, c)); });
    dl.append(el("dt", null, what), dd);
  }
  keys.append(el("h3", null, "Keyboard shortcuts"), dl);

  const about = el("section", "panel"), links = el("div", "row gap");
  const page = url => () => api("/api/browser/window", {method: "POST", body: {url}}).catch(e => toast(e.message, true));
  links.append(btn("Source code", "ghost", page("https://github.com/JrKrishh/teamloop-team"), "github"),
    btn("Website", "ghost", page("https://teamloop.vercel.app"), "globe"));
  about.append(el("h3", null, "About"), el("p", "sub", `Super Agents ${S.boot.version}. Open source under the MIT licence. The agents run on NVIDIA Nemotron through Nebius Token Factory.`), links);

  box.replaceChildren(acct, look, share, keys, about);
  if (S.team) hub(withTeam("sessions")).then(d => { if (share.isConnected) share.after(rulesCard(d.me)); }).catch(() => {});
}

start();
