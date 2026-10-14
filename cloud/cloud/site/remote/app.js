// Super Agents Remote: this phone drives Super Agents on your laptop. The turns run there; this shows your chats,
// sends messages, follows a turn live and answers its questions. Every message is sealed with AES-256-GCM under the
// key from the pairing code, which only this phone and the laptop have, so the relay in between passes on only noise.
"use strict";
const $ = id => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const icon = d => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("viewBox", "0 0 24 24"); const p = document.createElementNS(s.namespaceURI, "path"); p.setAttribute("d", d); s.append(p); return s; };
const enc = new TextEncoder(), dec = new TextDecoder();
const S = {pair: null, key: null, ws: null, ref: 0, beat: null, wait: 1000, joined: false, state: null, view: "pair",
  chat: null, turn: null, running: false, slots: {}, early: {}, pending: new Map(), seen: new Map()};

// ---- pairing. The QR link is /remote/#p=<channel>&k=<key>: the fragment never reaches a server, and it leaves the
// address bar at once. The key is kept in IndexedDB as a CryptoKey that can't be exported: this page can use it,
// but no script can read it back.
function store(mode, fn) {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open("sa-remote", 1);
    open.onupgradeneeded = () => open.result.createObjectStore("pair");
    open.onerror = () => reject(open.error);
    open.onsuccess = () => {
      const tx = open.result.transaction("pair", mode), req = fn(tx.objectStore("pair"));
      tx.oncomplete = () => resolve(req.result); tx.onerror = () => reject(tx.error);
    };
  });
}
async function loadPair() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (/^[0-9a-f]{32}$/.test(h.get("p") || "") && h.get("k")) {
    history.replaceState(null, "", location.pathname);
    S.pair = {p: h.get("p")};
    S.key = await crypto.subtle.importKey("raw", unb64(h.get("k")), "AES-GCM", false, ["encrypt", "decrypt"]);
    await store("readwrite", s => s.put({p: S.pair.p, key: S.key}, "me")).catch(() => {});  // else paired for this visit only
    return;
  }
  const kept = await store("readonly", s => s.get("me")).catch(() => null);
  if (kept && kept.p && kept.key) { S.pair = {p: kept.p}; S.key = kept.key; }
}

// ---- the seal: AES-256-GCM with the channel bound in, the same as the laptop's
const b64 = buf => { const u = new Uint8Array(buf); let s = ""; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); };
const unb64 = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), c => c.charCodeAt(0));
async function seal(msg) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const c = await crypto.subtle.encrypt({name: "AES-GCM", iv, additionalData: enc.encode(S.pair.p)}, S.key, enc.encode(JSON.stringify(msg)));
  return {iv: b64(iv), c: b64(c)};
}
async function unseal(env) {
  const p = await crypto.subtle.decrypt({name: "AES-GCM", iv: unb64(env.iv), additionalData: enc.encode(S.pair.p)}, S.key, unb64(env.c));
  return JSON.parse(dec.decode(p));
}

// ---- the relay: Supabase Realtime, or the hub's own socket; both speak the Phoenix protocol
async function relayUrl() {
  const cfg = await (await fetch("/v1/config", {cache: "no-store"})).json();
  if (cfg.relay === "supabase") return `${cfg.supabase_url.replace(/^https:/, "wss:").replace(/\/$/, "")}/realtime/v1/websocket?apikey=${encodeURIComponent(cfg.supabase_key)}&vsn=1.0.0`;
  if (cfg.relay === "hub") return `${location.origin.replace(/^http/, "ws")}/v1/relay?vsn=1.0.0`;
  throw new Error("This server can't reach your laptop yet.");
}
const topic = () => `realtime:sa-${S.pair.p}`;
function raw(event, payload, t = topic()) { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify({topic: t, event, payload, ref: String(++S.ref)})); }
async function connect() {
  let url;
  try { url = await relayUrl(); } catch (e) { status("off", navigator.onLine ? e.message : "This phone is offline"); return retry(); }
  const ws = S.ws = new WebSocket(url);
  ws.onopen = () => {
    S.wait = 1000; raw("phx_join", {config: {broadcast: {self: false, ack: false}, presence: {key: ""}, private: false}});
    clearInterval(S.beat); S.beat = setInterval(() => raw("heartbeat", {}, "phoenix"), 25000);
  };
  ws.onmessage = ev => {
    let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (m.topic !== topic()) return;
    if (m.event === "phx_reply" && !S.joined) { S.joined = true; hello(); }
    else if (m.event === "broadcast" && m.payload && m.payload.payload) receive(m.payload.payload);
  };
  ws.onclose = () => { if (S.ws !== ws) return; S.joined = false; clearInterval(S.beat); status("off", "Reconnecting…"); retry(); };
}
function retry() { setTimeout(connect, S.wait); S.wait = Math.min(S.wait * 2, 30000); }

// A request to the laptop, answered by a message that names it (re); turn events arrive on their own.
async function send(msg, wait = 15000) {
  if (!S.joined) throw new Error("Not connected to your laptop yet.");
  const id = b64(crypto.getRandomValues(new Uint8Array(12)));
  raw("broadcast", {type: "broadcast", event: "m", payload: await seal({...msg, from: "phone", id, ts: Date.now()})});
  if (!wait) return null;
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => { S.pending.delete(id); status("off", "Your laptop isn't answering"); reject(new Error("Your laptop didn't answer. Is Super Agents open on it?")); }, wait);
    S.pending.set(id, m => { clearTimeout(t); S.pending.delete(id); if (m.t === "error") reject(new Error(m.error)); else resolve(m); });
  });
}
async function receive(env) {
  let m; try { m = await unseal(env); } catch (e) { return; }  // not sealed with this phone's key
  const now = Date.now();
  if (m.from !== "laptop" || typeof m.ts !== "number" || Math.abs(now - m.ts) > 120000 || S.seen.has(m.id)) return;
  S.seen.set(m.id, now); for (const [k, t] of S.seen) if (now - t > 240000) S.seen.delete(k);
  status("on", S.state ? `Online · ${S.state.laptop}` : "Laptop online");
  if (m.re && S.pending.has(m.re)) S.pending.get(m.re)(m);
  else if (m.t === "events") onEvents(m.turn, m.events || []);
}
function deviceName() {
  const ua = navigator.userAgent;
  const os = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android phone" : "Browser";
  const br = /Edg\//.test(ua) ? "Edge" : /CriOS|Chrome/.test(ua) ? "Chrome" : /Firefox|FxiOS/.test(ua) ? "Firefox" : /Safari/.test(ua) ? "Safari" : "";
  return br ? `${os} · ${br}` : os;
}
async function hello(tries = 0) {
  status("", "Finding your laptop…");
  try {
    S.state = await send({t: "hello", device: deviceName()}, 5000);
    const sel = $("agent"), was = sel.value; sel.replaceChildren();
    for (const a of S.state.agents) { const o = el("option", null, a.name); o.value = a.id; sel.append(o); }
    sel.value = was || "agent-s";
    if (S.view === "home") showHome();
    if (S.turn && S.running) send({t: "watch", turn: S.turn, after: (S.slots[S.turn] || {}).next || 0}).catch(() => {});  // what it missed
  } catch (e) {
    if (tries < 5 && S.joined) setTimeout(() => hello(tries + 1), 2000);  // the laptop may still be joining (it was just paired, or it restarted)
    else toast(e.message, true);
  }
}
function status(cls, text) { const s = $("status"); s.className = cls; s.querySelector("span").textContent = text; }
function toast(text, bad) {
  const t = $("toast"); t.textContent = text; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, 4000);
}
const agentOf = id => ((S.state && S.state.agents) || []).find(a => a.id === id) || {id, name: id === "agent-s" ? "Agent S" : "Agent", color: ""};
function ago(t) { const s = Math.max(0, Date.now() / 1000 - t); return s < 60 ? "now" : s < 3600 ? `${Math.round(s / 60)} min` : s < 86400 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} d`; }

// ---- views
function show(view) {
  S.view = view;
  for (const v of ["pair", "home", "chat"]) $(v).hidden = v !== view;
  $("back").hidden = view !== "chat"; $("newChat").hidden = view !== "home"; $("composer").hidden = view === "pair";
}
const laptopName = () => (S.state && S.state.user ? `${S.state.user.split(" ")[0]}'s laptop` : "Your laptop");
function showHome() {
  show("home"); S.chat = null;
  $("title").textContent = S.state ? laptopName() : "Super Agents";
  const live = $("live"); live.replaceChildren();
  for (const t of (S.state && S.state.live) || []) {
    const b = el("button", t.asking ? "asking" : null); b.type = "button";
    b.append(el("small", null, `${agentOf(t.agent).name} ${t.asking ? "needs you" : "is working"}`), el("span", null, t.message));
    b.onclick = () => openChat(t.chat, t);
    live.append(b);
  }
  const ul = $("chats"); ul.replaceChildren();
  for (const c of (S.state && S.state.chats) || []) {
    const li = el("li"), b = el("button"); b.type = "button";
    b.append(el("b", null, c.title || "Untitled chat"), el("small", null, ago(c.updated)), el("span", "who", agentOf(c.agent).name));
    b.onclick = () => openChat(c.id); li.append(b); ul.append(li);
  }
  if (!ul.children.length) ul.append(el("li", "none", "No chats yet. Write one below."));
  const forget = el("li", "none"), f = el("button", null, "Forget this laptop"); f.type = "button";
  f.onclick = () => store("readwrite", s => s.delete("me")).catch(() => {}).then(() => location.reload());
  forget.append(f); ul.append(forget);
}
async function openChat(cid, live) {
  show("chat"); S.chat = cid; S.turn = null; running(false);
  const thread = $("thread"); thread.replaceChildren(el("div", "thinking", "Opening…"));
  try {
    // a chat is saved when its first turn ends: one still on its first turn has only the live turn to show
    const c = await send({t: "chat", chat: cid}).then(m => m.chat, e => { if (live) return {title: live.message, view: []}; throw e; });
    $("title").textContent = c.title || "Chat"; thread.replaceChildren();
    for (const v of c.view || []) {
      userMsg(v.user); const slot = agentMsg(v.agent || c.agent);
      for (const e of v.events || []) onEvent(slot, e, true);
      finish(slot, v.answer);
    }
    if (c.agent) $("agent").value = c.agent;
    live = live || ((S.state && S.state.live) || []).find(t => t.chat === cid);
    if (live) watch(live);
    scrollDown(true);
  } catch (e) { thread.replaceChildren(el("p", "answer fail", e.message)); }
}
function watch(t) {  // a turn running on the laptop, maybe started at the desk
  userMsg(t.message); const slot = agentMsg(t.agent); slot.turn = t.turn;
  S.slots[t.turn] = slot; S.turn = t.turn; running(true);
  send({t: "watch", turn: t.turn, after: 0}).catch(e => toast(e.message, true));
}
function running(on) {
  S.running = on; const b = $("send");
  b.classList.toggle("stop", on); b.setAttribute("aria-label", on ? "Stop" : "Send");
  b.replaceChildren(icon(on ? "M7 7h10v10H7z" : "M12 19V5M6 11l6-6 6 6"));
}
function scrollDown(force) {
  const m = document.querySelector("main");
  if (force || m.scrollHeight - m.scrollTop - m.clientHeight < 240) requestAnimationFrame(() => m.scrollTo({top: m.scrollHeight}));
}

// ---- a turn: its steps fold into one line; what waits for you stays in view; then the answer
function userMsg(text) { $("thread").append(el("div", "msg user", text)); scrollDown(true); }
function agentMsg(agentId) {
  const a = agentOf(agentId), m = el("div", "msg agent"), who = el("div", "who"), dot = el("i");
  if (a.color) dot.style.setProperty("--c", a.color);
  who.append(dot, a.name);
  const box = el("div", "steps-box collapsed"), head = el("button", "steps-head"), steps = el("div", "steps"), needs = el("div", "needs");
  head.type = "button"; head.setAttribute("aria-expanded", "false"); box.hidden = true;
  head.onclick = () => head.setAttribute("aria-expanded", String(!box.classList.toggle("collapsed")));
  box.append(head, steps);
  const line = el("div", "thinking", "Thinking…");
  m.append(who, box, needs, line); $("thread").append(m); scrollDown();
  return {agent: agentId, m, who, box, head, steps, needs, line, cards: {}, next: 0, buf: new Map(), asked: 0, turn: null};
}
const SAID = [[/^read_file$/, "read a file", "read # files"], [/^(search_files|list_files)$/, "looked through the code", "looked through the code # times"],
  [/^write_file$/, "edited a file", "edited # files"], [/^run_command$/, "ran a command", "ran # commands"],
  [/^(git_|github_pr$|open_pr$)/, "used git", "took # git steps"], [/^(browser_|fetch_url$|dev_server$)/, "used the browser", "took # browser steps"],
  [/^desktop_/, "used an app", "took # desktop steps"], [/^mcp__/, "used a connector", "made # connector calls"], [/./, "looked up the team", "took # team steps"]];
const LABEL = {run_command: ["Run", a => a.command], read_file: ["Read", a => a.path], write_file: ["Write", a => a.path],
  list_files: ["List", a => a.path || "connected repos"], search_files: ["Search", a => a.query], git_commit: ["Commit", a => (a.message || "").split("\n")[0]],
  git_push: ["Push", a => a.repo || "this branch"], open_pr: ["Pull request", a => a.title], fetch_url: ["Read page", a => a.url],
  browser_open: ["Open", a => a.url], team_board: ["Read the board", () => ""], team_ask: ["Asked the team's history", a => a.question],
  create_task: ["Create task", a => a.title], assign_task: ["Assign", a => `${a.task} → ${a.owner}`], close_task: ["Close", a => a.task],
  desktop_open: ["Open app", a => a.app], share_files: ["Share", a => (a.paths || []).join(", ")]};
const STATUS = {running: "running", asking: "needs you", planned: "planned", done: "✓ done", failed: "✕ failed", declined: "declined", discarded: "discarded", undone: "undone"};
function label(e) {
  const a = e.args || {}, l = LABEL[e.name];
  if (l) return [l[0], String(l[1](a) || "")];
  const n = (/^mcp__.+?__(.+)$/.exec(e.name) || [, e.name])[1].replace(/_/g, " ");
  return [n[0].toUpperCase() + n.slice(1), Object.values(a).filter(v => typeof v === "string").join(" · ").slice(0, 120)];
}
function head(slot) {
  const cards = Object.values(slot.cards).filter(c => c.box.parentElement === slot.steps);
  slot.box.hidden = !cards.length && !slot.steps.querySelector(".narr");
  if (slot.box.hidden) return;
  const counts = new Map(); let failed = 0, skipped = 0, now = null;
  for (const c of cards) {
    if (["asking", "planned", "discarded", "declined"].includes(c.status)) { skipped++; continue; }
    const k = SAID.find(([re]) => re.test(c.e.name)); counts.set(k, (counts.get(k) || 0) + 1);
    if (c.status === "failed") failed++;
    if (c.status === "running") now = c;
  }
  const said = [...counts].map(([[, one, many], n]) => (n === 1 ? one : many.replace("#", n))).join(", ") || (skipped ? "" : "Notes along the way");
  slot.head.replaceChildren(icon("m9 6 6 6-6 6"));
  if (said) slot.head.append(el("span", "said", said[0].toUpperCase() + said.slice(1)));
  if (skipped) slot.head.append(el("span", "bad", `${skipped} not run`));
  if (failed) slot.head.append(el("span", "bad", `${failed} failed`));
  if (now) slot.head.append(el("span", "now", label(now.e).join(" ").trim()));
}
// Events are shown strictly in order. A gap means a message was lost on the way (the relay keeps nothing): ask the
// laptop for everything after the last one shown, at most every 3 s; duplicates are dropped.
function onEvents(turn, evs) {
  const slot = S.slots[turn];
  if (!slot) { (S.early[turn] = S.early[turn] || []).push(...evs); return; }  // came before the laptop said which turn it is
  for (const e of evs) if (e.i >= slot.next) slot.buf.set(e.i, e);
  while (slot.buf.has(slot.next)) { const e = slot.buf.get(slot.next); slot.buf.delete(slot.next); slot.next++; onEvent(slot, e, false); }
  if (slot.buf.size) catchUp(slot);
}
function catchUp(slot) {
  if (!slot.turn || Date.now() - slot.asked < 3000) return;
  slot.asked = Date.now(); send({t: "watch", turn: slot.turn, after: slot.next}).catch(() => {});
}
function onEvent(slot, e, past) {
  if (e.kind === "thinking") { slot.line.textContent = "Thinking…"; slot.m.append(slot.line); }
  else if (e.kind === "text") { slot.steps.append(el("div", "narr", e.text)); head(slot); }
  else if (e.kind === "tool") {
    card(slot, e, past);
    if (!past && (e.status === "asking" || e.status === "running")) { slot.line.textContent = e.status === "asking" ? "Waiting for you…" : "Working…"; slot.m.append(slot.line); }
  } else if (e.kind === "answer") finish(slot, e.text);
  else if (e.kind === "error") { slot.line.remove(); slot.m.append(el("div", "answer fail", e.text)); }
  else if (e.kind === "end") {
    if (slot.m.querySelector(".answer")) slot.line.remove();
    if (e.planned && !past) planFoot(slot, e.planned);
    if (S.turn === slot.turn) running(false);
    send({t: "hello", device: deviceName()}).then(m => { S.state = m; }).catch(() => {});  // the chat list moved
  }
  if (!past) scrollDown();
}
function card(slot, e, past) {
  let c = slot.cards[e.id];
  if (!c) {
    const box = el("div", "tool"), row = el("div", "tool-row"), [lab, targ] = label(e), st = el("span", "st");
    row.append(el("b", null, lab), el("span", "targ", targ), st); box.append(row);
    c = slot.cards[e.id] = {box, row, st, e, out: null, result: null};
    row.onclick = () => {
      if (!c.result) return;
      if (c.out) { c.out.remove(); c.out = null; } else { c.out = el("pre", null, c.result); row.after(c.out); }
    };
  }
  c.e = {...c.e, ...e}; c.status = e.status;
  if (e.result != null) { c.result = e.result; if (c.out) c.out.textContent = e.result; }
  const did = /^(desktop|browser)_(click|type|select|scroll)$/.test(e.name) && /^(?:Pressed|Clicked|Filled|Typed into|Chose|Scrolled) (.+)\.$/m.exec((c.result || "").split("\n")[0]);
  if (did) c.row.querySelector(".targ").textContent = did[1];
  c.box.className = `tool ${e.status}`; c.st.textContent = STATUS[e.status] || e.status;
  const ask = c.box.querySelector(".ask"); if (ask) ask.remove();
  if (e.status === "asking" && !past) c.box.append(askBox(slot, c));
  const home = !past && (e.status === "asking" || e.status === "planned") ? slot.needs : slot.steps;
  if (c.box.parentElement !== home) home.append(c.box);
  head(slot);
}
function askBox(slot, c) {
  const e = c.e, a = e.args || {}, who = agentOf(slot.agent).name, box = el("div", "ask");
  const detail = e.name === "run_command" ? a.command : e.name === "write_file" ? a.content
    : e.name === "git_commit" ? `${a.message || ""}\n\n${(a.files || []).join("\n")}` : JSON.stringify(a, null, 2);
  box.append(el("p", null, e.name === "run_command" ? `${who} wants to run this on your laptop${a.cwd ? ` in ${a.cwd}` : ""}:`
    : `${who} wants to ${label(e)[0].toLowerCase()}${label(e)[1] ? ` ${label(e)[1]}` : ""}:`));
  if (detail && detail !== "{}") box.append(el("pre", null, String(detail)));
  const no = el("button", "btn", "Deny"), yes = el("button", "btn primary", e.name === "run_command" ? "Run it" : "Allow");
  no.type = yes.type = "button";
  const decide = async ok => {
    no.disabled = yes.disabled = true;
    try { await send({t: "decide", turn: slot.turn, call: e.id, approve: ok}); } catch (err) { toast(err.message, true); no.disabled = yes.disabled = false; }
  };
  no.onclick = () => decide(false); yes.onclick = () => decide(true);
  const btns = el("div", "btns"); btns.append(no, yes); box.append(btns);
  return box;
}
function planFoot(slot, n) {
  const box = el("div", "plan-foot"), t = el("span");
  t.append(el("b", null, `${n} change${n > 1 ? "s" : ""} planned.`), " Nothing has changed yet.");
  const no = el("button", "btn", "Discard"), go = el("button", "btn primary", "Run plan"); no.type = go.type = "button";
  no.onclick = () => {
    for (const c of Object.values(slot.cards)) if (c.status === "planned") card(slot, {...c.e, status: "discarded"}, true);
    box.replaceChildren(el("span", null, "Plan discarded. Nothing changed."));
  };
  go.onclick = async () => {
    no.disabled = go.disabled = true;
    try { await send({t: "run_plan", turn: slot.turn}); box.remove(); S.turn = slot.turn; running(true); }
    catch (e) { toast(e.message, true); no.disabled = go.disabled = false; }
  };
  box.append(t, no, go); slot.m.append(box);
}
function finish(slot, text) { slot.line.remove(); if (text) slot.m.append(md(text)); }

// ---- answers in Markdown, built as elements (never as HTML, so nothing an agent writes can run here)
function md(text) {
  const root = el("div", "answer md"), lines = String(text).split("\n");
  let i = 0, list = null;
  while (i < lines.length) {
    const l = lines[i];
    if (/^```/.test(l)) {
      const code = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
      i++; const pre = el("pre"); pre.append(el("code", null, code.join("\n"))); root.append(pre); list = null; continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(l);
    if (h) { root.append(inline(el(h[1].length < 3 ? "h3" : "h4"), h[2])); list = null; i++; continue; }
    const li = /^\s*(?:[-*]|(\d+)\.)\s+(.*)$/.exec(l);
    if (li) {
      const tag = li[1] ? "OL" : "UL";
      if (!list || list.tagName !== tag) { list = el(tag.toLowerCase()); root.append(list); }
      list.append(inline(el("li"), li[2])); i++; continue;
    }
    if (!l.trim()) { list = null; i++; continue; }
    const para = [l]; i++;
    while (i < lines.length && lines[i].trim() && !/^(```|#{1,4}\s|\s*(?:[-*]|\d+\.)\s)/.test(lines[i])) para.push(lines[i++]);
    root.append(inline(el("p"), para.join(" "))); list = null;
  }
  return root;
}
function inline(node, s) {
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))/g;
  let last = 0, m;
  while ((m = re.exec(s))) {
    if (m.index > last) node.append(s.slice(last, m.index));
    if (m[1]) node.append(el("code", null, m[1].slice(1, -1)));
    else if (m[2]) node.append(el("strong", null, m[2].slice(2, -2)));
    else if (m[3]) node.append(el("em", null, m[3].slice(1, -1)));
    else { const a = el("a", null, m[5]); a.href = m[6]; a.target = "_blank"; a.rel = "noopener"; node.append(a); }
    last = re.lastIndex;
  }
  if (last < s.length) node.append(s.slice(last));
  return node;
}

// ---- the composer
const input = $("input");
const autosize = () => { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 160)}px`; };
input.addEventListener("input", autosize);
$("agent").onchange = () => { const a = agentOf($("agent").value); if (a.mode) $("mode").value = a.mode; };
$("composer").onsubmit = async ev => {
  ev.preventDefault();
  if (S.running && S.turn) { send({t: "stop", turn: S.turn}).catch(e => toast(e.message, true)); return; }
  const text = input.value.trim(); if (!text) return;
  if (S.view !== "chat") { show("chat"); $("thread").replaceChildren(); $("title").textContent = "New chat"; S.chat = null; }
  input.value = ""; autosize();
  userMsg(text); const slot = agentMsg($("agent").value); running(true);
  try {
    const r = await send({t: "send", chat: S.chat, agent: $("agent").value, mode: $("mode").value, message: text});
    S.chat = r.chat; S.turn = slot.turn = r.turn; S.slots[r.turn] = slot;
    const early = S.early[r.turn] || []; delete S.early[r.turn]; onEvents(r.turn, early);
  } catch (e) { slot.line.remove(); slot.m.append(el("div", "answer fail", e.message)); running(false); }
};
$("back").onclick = () => { S.turn = null; running(false); showHome(); send({t: "hello", device: deviceName()}).then(m => { S.state = m; if (S.view === "home") showHome(); }).catch(() => {}); };
$("newChat").onclick = () => { show("chat"); $("thread").replaceChildren(); $("title").textContent = "New chat"; S.chat = null; S.turn = null; running(false); input.focus(); };
setInterval(() => {  // keeps "online" fresh; while a turn runs, also fetches anything lost at its very end
  if (!S.joined || document.visibilityState !== "visible") return;
  if (S.running && S.slots[S.turn]) catchUp(S.slots[S.turn]); else send({t: "ping"}).catch(() => {});
}, 30000);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && S.joined) hello(); });

// ---- start
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
if (!window.crypto || !crypto.subtle) { show("pair"); status("off", "Needs a secure (https) page"); }
else loadPair().then(() => {
  if (!S.key) { show("pair"); status("off", "Not paired"); return; }
  show("home"); $("chats").replaceChildren(el("li", "none", "Waiting for your laptop…")); connect();
}, () => { show("pair"); status("off", "Not paired"); toast("That pairing code didn't work. Pair again from the laptop.", true); });
