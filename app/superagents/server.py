"""The app's local server. The window's UI talks only to this (same origin, no CORS); this talks to the hub with the
person's session, to Supabase for sign-in, and to the connector on this laptop.

It listens on 127.0.0.1 only. Every /api call must carry the per-launch key the window got in its URL fragment, and
the Host header must be ours, so neither a web page nor a DNS-rebinding trick can drive it.
"""

from __future__ import annotations

import asyncio
import json
import platform
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, laptop, store, supa
from .runtime import agents as agent_store
from .runtime import loop as runtime_loop
from .runtime import mcpman
from .runtime import skills as skill_store
from .runtime import terminal as terminal_mod
from .runtime import tools as runtime_tools

UI = Path(__file__).parent / "ui"
# what the UI may ask the hub for, through /api/cloud/<path>
CLOUD_PATHS = re.compile(r"^(me|teams|board|team|ask|tasks|digest|refresh|settings|events|usage"
                         r"|teams/[0-9a-f-]{36}/(invites|members/[0-9a-f-]{36}(/restore)?)"
                         r"|invites/[A-Za-z0-9_-]{8,80}(/accept)?|tasks/[A-Za-z0-9_.-]{1,40})$")


class State:
    def __init__(self, cloud_url: str, port: int = 0, key: Optional[str] = None) -> None:
        self.cloud = cloud_url.rstrip("/")
        self.port = port
        self.key = key or secrets.token_urlsafe(24)
        self.flows: dict[str, str] = {}  # pending GitHub sign-in: flow id -> PKCE verifier
        self.auth: dict = {"state": "idle"}
        self.window = None  # the pywebview window, for the folder picker and bringing the app to the front
        self.supabase: Optional[dict] = None
        self.turns: dict[str, runtime_loop.Turn] = {}
        self._mcp: Optional[mcpman.Manager] = None
        self.open_window: Optional[Callable[[str], None]] = None  # a second app window for the browser panel

    @property
    def mcp(self) -> mcpman.Manager:
        if self._mcp is None:
            self._mcp = mcpman.Manager()
        return self._mcp


def cloud(state: State, method: str, path: str, body: Optional[dict] = None, query: Optional[dict] = None,
          token: Optional[str] = None) -> tuple[int, dict]:
    """A hub call with the person's session. Returns (status, JSON); 503 when the hub can't be reached."""
    url = state.cloud + path + ("?" + urllib.parse.urlencode(query) if query else "")
    headers = {"Content-Type": "application/json", "User-Agent": f"SuperAgents/{__version__}"}
    tok = store.load().get("session") if token is None else token
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None, headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {"detail": f"The server said {e.code}"}
    except OSError:
        return 503, {"detail": "Can't reach Super Agents right now. Check your connection."}


def supabase_config(state: State) -> dict:
    if not state.supabase:
        code, cfg = cloud(state, "GET", "/v1/config", token="")
        if code != 200 or not cfg.get("supabase_url"):
            raise HTTPException(503, "Sign-in isn't available right now. Check your connection.")
        state.supabase = cfg
    return state.supabase


def finish_sign_in(state: State, session: dict) -> None:
    """A Supabase session -> the hub's own session, kept in ~/.teamloop/app.json."""
    code, body = cloud(state, "POST", "/v1/app/session", {"access_token": session["access_token"]}, token="")
    if code != 200:
        raise supa.AuthError(body.get("detail") or "Sign-in didn't go through. Try again.")
    old = store.load()
    new = {"session": body["token"], "user_id": body["user"]["id"], "profile": supa.profile(session)}
    if old.get("user_id") == new["user_id"]:
        new["team"] = old.get("team")
    else:
        laptop.disconnect()  # someone else signed in on this laptop: stop reporting under the previous name
    store.save(new)


def bring_to_front(state: State) -> None:
    w = state.window
    if w is None:
        return
    try:
        w.restore()
        w.on_top = True
        time.sleep(0.3)
        w.on_top = False
    except Exception:  # noqa: BLE001 - nice to have
        pass


def callback_page(title: str, text: str, ok: bool) -> str:
    colour = "#4CC38A" if ok else "#F07A70"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Super Agents</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#121114;color:#F3ECE0;
font:16px/1.5 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif}}main{{text-align:center;max-width:420px;padding:24px}}
h1{{font:800 26px/1.2 "Segoe UI Variable Display","Segoe UI",system-ui,sans-serif;margin:18px 0 6px}}p{{color:#A39B90;margin:0}}
i{{display:inline-block;width:10px;height:10px;border-radius:50%;background:{colour};margin-right:8px}}</style></head>
<body><main><svg width="72" height="72" viewBox="0 0 100 100" aria-hidden="true"><path fill="#C2554C" d="M50 95C30 95 14 93 11 86C8.5 80 9 68 9.5 56C11 31 27 14 48 12.5C56 12 63 9.5 70 3.5C71.2 9.5 69.8 14.5 66.5 17.8C81 25 90 39 90.5 56C91 68 91.5 80 89 86C86 93 70 95 50 95Z"/><ellipse fill="#F4E6D8" cx="50" cy="61" rx="30" ry="27"/><ellipse fill="#18171B" cx="38.5" cy="62" rx="6.2" ry="7.8"/><ellipse fill="#18171B" cx="61.5" cy="62" rx="6.2" ry="7.8"/></svg>
<h1><i></i>{title}</h1><p>{text}</p></main></body></html>"""


class EmailIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    mode: str = Field(default="signin", pattern="^(signin|signup)$")
    name: str = Field(default="", max_length=64)


class TeamIn(BaseModel):
    team: str = Field(min_length=36, max_length=36)


class RepoIn(BaseModel):
    path: Optional[str] = Field(default=None, max_length=1000)


class PauseIn(BaseModel):
    paused: bool


class ThemeIn(BaseModel):
    dark: bool


class PrefsIn(BaseModel):
    theme: Optional[str] = Field(default=None, pattern="^(dark|light)$")
    mode: Optional[str] = Field(default=None, pattern="^(plan|manual|auto)$")
    model: Optional[str] = Field(default=None, pattern="^(auto|lightning|super|ultra)$")
    agent: Optional[str] = Field(default=None, pattern="^[a-z0-9-]{3,40}$")


class AgentBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=40)
    color: Optional[str] = Field(default=None, max_length=9)
    instructions: Optional[str] = Field(default=None, max_length=8000)
    model: Optional[str] = Field(default=None, pattern="^(auto|lightning|super|ultra)$")
    mode: Optional[str] = Field(default=None, pattern="^(manual|auto|plan)$")
    skills: Optional[list[str]] = None
    connectors: Optional[list[str]] = None
    tools: Optional[dict] = None


class SkillBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=400)
    body: str = Field(min_length=1, max_length=100_000)


class NameBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class ConnectorBody(BaseModel):
    preset: Optional[str] = None
    values: dict = Field(default_factory=dict)
    name: Optional[str] = Field(default=None, max_length=40)
    url: Optional[str] = Field(default=None, max_length=500)
    headers: dict = Field(default_factory=dict)
    command: Optional[str] = Field(default=None, max_length=300)
    args: list[str] = Field(default_factory=list, max_length=40)
    env: dict = Field(default_factory=dict)


class EnabledBody(BaseModel):
    enabled: bool


class TurnBody(BaseModel):
    chat: Optional[str] = Field(default=None, max_length=40)
    agent: str = Field(default="agent-s", max_length=40)
    message: str = Field(min_length=1, max_length=8000)
    attachments: list[dict] = Field(default_factory=list, max_length=5)
    mode: str = Field(default="manual", pattern="^(manual|auto|plan)$")
    model: str = Field(default="auto", pattern="^(auto|lightning|super|ultra)$")
    team: str = Field(min_length=36, max_length=36)


class DecideBody(BaseModel):
    call: str = Field(min_length=1, max_length=100)
    approve: bool


class UrlBody(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


IMAGES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
          ".svg": "image/svg+xml", ".ico": "image/x-icon", ".bmp": "image/bmp"}
ISSUES_MAX = 50


def github_issues(repo: str) -> dict:
    """Open issues of a public GitHub repo, as text Agent S can plan from. Pull requests are left out."""
    url = f"https://api.github.com/repos/{repo}/issues?state=open&per_page={ISSUES_MAX}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": f"SuperAgents/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            items = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise HTTPException(404 if e.code == 404 else 502,
                            "No such public repo (private repos aren't supported yet)" if e.code == 404 else f"GitHub said {e.code}") from None
    except OSError:
        raise HTTPException(503, "Can't reach GitHub right now") from None
    lines = []
    for i in items:
        if "pull_request" in i:
            continue
        labels = ", ".join(lb.get("name", "") for lb in i.get("labels") or [])
        body = " ".join((i.get("body") or "").split())[:300]
        lines.append(f"#{i['number']} {i['title']}" + (f"  [{labels}]" if labels else "") + (f"\n   {body}" if body else ""))
    return {"name": f"{repo} issues ({len(lines)})", "text": "\n".join(lines) or "(no open issues)", "count": len(lines)}


def create(state: State, open_url: Callable[[str], object] = webbrowser.open,
           pick_folder: Optional[Callable[[], Optional[str]]] = None,
           set_title_theme: Optional[Callable[[bool], None]] = None) -> FastAPI:
    app = FastAPI(title="Super Agents", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.headers.get("host") not in (f"127.0.0.1:{state.port}", f"localhost:{state.port}"):
            return JSONResponse({"detail": "Not here."}, 403)
        if request.url.path.startswith("/api/") and not secrets.compare_digest(
                request.headers.get("x-app-key", ""), state.key):
            return JSONResponse({"detail": "Not allowed."}, 403)
        return await call_next(request)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(UI / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/ui", StaticFiles(directory=UI), name="ui")

    # ---- who's here ---------------------------------------------------------------------------------
    @app.get("/api/boot")
    def boot() -> dict:
        s = store.load()
        out = {"version": __version__, "cloud": state.cloud, "signed_in": False, "user": None, "teams": [],
               "team": None, "laptop": laptop.status(), "offline": None, "prefs": s.get("prefs") or {"theme": "dark"}}
        if not s.get("session"):
            return out
        code, me = cloud(state, "GET", "/v1/me")
        if code == 200 and me.get("user"):
            teams = me.get("teams") or []
            team = s.get("team") if any(t["id"] == s.get("team") for t in teams) else (teams[0]["id"] if teams else None)
            out.update(signed_in=True, user={**me["user"], **{k: v for k, v in (s.get("profile") or {}).items() if k == "avatar"}},
                       teams=teams, team=team)
        elif code in (200, 401):  # the session expired or was revoked: sign in again
            store.save({k: v for k, v in s.items() if k != "session"})
        else:
            out["offline"] = me.get("detail")
        return out

    # ---- sign-in ------------------------------------------------------------------------------------
    @app.post("/api/auth/github")
    def auth_github() -> dict:
        cfg = supabase_config(state)
        flow = secrets.token_urlsafe(16)
        verifier, challenge = supa.pkce_pair()
        state.flows = {flow: verifier}  # one sign-in at a time; a newer click wins
        state.auth = {"state": "waiting"}
        url = supa.authorize_url(cfg["supabase_url"], f"http://127.0.0.1:{state.port}/auth/callback?flow={flow}", challenge)
        open_url(url)
        return {"url": url}

    @app.get("/auth/callback", include_in_schema=False)
    def auth_callback(flow: str = "", code: str = "", error: str = "", error_description: str = "") -> HTMLResponse:
        verifier = state.flows.pop(flow, None)
        if error or not code or not verifier:
            why = error_description or ("This sign-in link was already used or has expired." if not verifier else "Sign-in was cancelled.")
            state.auth = {"state": "error", "error": why}
            return HTMLResponse(callback_page("Sign-in didn't finish", f"{why} Go back to Super Agents and try again.", False), 400)
        try:
            cfg = supabase_config(state)
            finish_sign_in(state, supa.exchange_code(cfg["supabase_url"], cfg["supabase_key"], code, verifier))
        except (supa.AuthError, HTTPException) as e:
            state.auth = {"state": "error", "error": getattr(e, "detail", None) or str(e)}
            return HTMLResponse(callback_page("Sign-in didn't finish", f"{state.auth['error']} Go back to Super Agents and try again.", False), 400)
        state.auth = {"state": "done"}
        threading.Thread(target=bring_to_front, args=(state,), daemon=True).start()
        return HTMLResponse(callback_page("You're signed in", "Head back to Super Agents. You can close this tab.", True))

    @app.get("/api/auth/status")
    def auth_status() -> dict:
        return state.auth

    @app.post("/api/auth/cancel")
    def auth_cancel() -> dict:
        state.flows.clear()
        state.auth = {"state": "idle"}
        return state.auth

    @app.post("/api/auth/email")
    def auth_email(body: EmailIn) -> dict:
        cfg = supabase_config(state)
        try:
            if body.mode == "signin":
                session = supa.password(cfg["supabase_url"], cfg["supabase_key"], body.email.strip(), body.password)
            else:
                session = supa.signup(cfg["supabase_url"], cfg["supabase_key"], body.email.strip(), body.password,
                                      body.name.strip())
            if not session.get("access_token"):
                return {"confirm": True}
            finish_sign_in(state, session)
        except supa.AuthError as e:
            raise HTTPException(401, str(e)) from None
        return {"ok": True}

    @app.post("/api/auth/signout")
    def auth_signout() -> dict:
        cloud(state, "POST", "/v1/logout")
        store.clear()
        laptop.disconnect()
        state.auth = {"state": "idle"}
        return {"ok": True}

    # ---- the hub, through us ------------------------------------------------------------------------
    @app.api_route("/api/cloud/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"])
    async def to_cloud(path: str, request: Request) -> JSONResponse:
        if not CLOUD_PATHS.match(path):
            raise HTTPException(404, "Not a Super Agents call")
        body = None
        if request.method in ("POST", "PATCH"):
            raw = await request.body()
            body = json.loads(raw) if raw else {}
        code, data = await run_in_threadpool(cloud, state, request.method, f"/v1/{path}", body,
                                             dict(request.query_params) or None)
        return JSONResponse(data, code)

    @app.post("/api/team")
    def pick_team(body: TeamIn) -> dict:
        s = store.load()
        s["team"] = body.team
        store.save(s)
        return {"team": body.team}

    # ---- this laptop --------------------------------------------------------------------------------
    @app.get("/api/laptop")
    def laptop_status() -> dict:
        return laptop.status()

    @app.post("/api/laptop/team")
    def laptop_team(body: TeamIn) -> dict:
        code, link = cloud(state, "POST", f"/v1/teams/{body.team}/connector", {"label": platform.node()[:40]})
        if code != 200:
            raise HTTPException(code, link.get("detail") or "Couldn't connect this laptop.")
        laptop.connect_team(state.cloud, link)
        return laptop.status()

    @app.post("/api/laptop/repos")
    def laptop_repo(body: RepoIn) -> dict:
        path = body.path or (pick_folder() if pick_folder else None)
        if not path:
            return {"cancelled": True}
        return laptop.connect_repo(path)

    @app.post("/api/laptop/pause")
    def laptop_pause(body: PauseIn) -> dict:
        laptop.set_paused(body.paused)
        return laptop.status()

    @app.post("/api/laptop/send")
    def laptop_send() -> dict:
        return laptop.send_now()

    @app.post("/api/window/theme")
    def window_theme(body: ThemeIn) -> dict:
        if set_title_theme:
            set_title_theme(body.dark)
        return {"ok": True}

    @app.post("/api/prefs")
    def prefs(body: PrefsIn) -> dict:
        s = store.load()
        s["prefs"] = {**(s.get("prefs") or {}), **body.model_dump(exclude_none=True)}
        store.save(s)
        return s["prefs"]

    @app.post("/api/pick-folder")
    def pick_a_folder() -> dict:
        path = pick_folder() if pick_folder else None
        return {"path": path} if path else {"cancelled": True}

    @app.get("/api/import/github")
    def import_github(repo: str) -> dict:
        repo = repo.strip().removeprefix("https://github.com/").strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repo):
            raise HTTPException(400, "Use owner/repo, for example vercel/next.js")
        return github_issues(repo)

    # ---- agents, skills, connectors ---------------------------------------------------------------------
    @app.get("/api/agents")
    def agents_list() -> dict:
        return {"agents": agent_store.all_agents(), "colors": list(agent_store.COLOURS)}

    @app.post("/api/agents")
    def agents_create(body: AgentBody) -> dict:
        return agent_store.save(None, body.model_dump(exclude_none=True))

    @app.patch("/api/agents/{agent_id}")
    def agents_update(agent_id: str, body: AgentBody) -> dict:
        try:
            return agent_store.save(agent_id, body.model_dump(exclude_none=True))
        except KeyError:
            raise HTTPException(404, "No such agent") from None

    @app.delete("/api/agents/{agent_id}")
    def agents_delete(agent_id: str) -> dict:
        try:
            agent_store.delete(agent_id)
        except PermissionError as e:
            raise HTTPException(400, str(e)) from None
        return {"ok": True}

    def skill_info(s) -> dict:
        return {"name": s.name, "description": s.description, "bundled": s.bundled, "files": s.files(),
                "always": s.name in skill_store.DEFAULT_ON}

    @app.get("/api/skills")
    def skills_list() -> dict:
        return {"skills": [skill_info(s) for s in skill_store.all_skills().values()]}

    @app.get("/api/skills/claude-code")
    def skills_from_claude_code() -> dict:
        have = skill_store.all_skills()
        return {"skills": [{"name": s.name, "description": s.description, "installed": s.name in have}
                           for s in skill_store.claude_code_skills()]}

    @app.get("/api/skills/{name}")
    def skills_get(name: str) -> dict:
        s = skill_store.all_skills().get(name)
        if not s:
            raise HTTPException(404, "No such skill")
        return {**skill_info(s), "body": s.body()}

    @app.post("/api/skills")
    def skills_save(body: SkillBody) -> dict:
        try:
            return skill_info(skill_store.save(body.name.strip(), body.description, body.body))
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/skills/import")
    def skills_import(body: NameBody) -> dict:
        try:
            return skill_info(skill_store.import_claude_code(body.name))
        except FileNotFoundError:
            raise HTTPException(404, "No Claude Code skill with that name") from None

    @app.delete("/api/skills/{name}")
    def skills_delete(name: str) -> dict:
        try:
            skill_store.delete(name)
        except FileNotFoundError:
            raise HTTPException(404, "Only your own skills can be deleted") from None
        return {"ok": True}

    @app.get("/api/connectors")
    def connectors_list() -> dict:
        live = {cid: len(v[3]) for cid, v in state.mcp.live.items()} if state._mcp else {}
        return {"items": [mcpman.public(c) for c in mcpman.load()], "presets": mcpman.PRESETS,
                "errors": dict(state.mcp.errors) if state._mcp else {}, "live": live}

    @app.post("/api/connectors")
    def connectors_add(body: ConnectorBody) -> dict:
        try:
            c = mcpman.from_preset(body.preset, body.values) if body.preset else mcpman.custom(body.model_dump())
        except KeyError:
            raise HTTPException(400, "Unknown connector") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        mcpman.save_all(mcpman.load() + [c])
        return mcpman.public(c)

    @app.post("/api/connectors/{cid}/test")
    def connectors_test(cid: str) -> dict:
        c = next((c for c in mcpman.load() if c["id"] == cid), None)
        if not c:
            raise HTTPException(404, "No such connector")
        try:
            return {"tools": state.mcp.test(c)}
        except Exception as e:  # noqa: BLE001 - shown next to the connector
            raise HTTPException(502, f"Couldn't connect: {type(e).__name__}: {e}"[:300]) from None

    @app.patch("/api/connectors/{cid}")
    def connectors_toggle(cid: str, body: EnabledBody) -> dict:
        items = mcpman.load()
        for c in items:
            if c["id"] == cid:
                c["enabled"] = body.enabled
        mcpman.save_all(items)
        if state._mcp:
            state.mcp.drop(cid)
        return {"ok": True}

    @app.delete("/api/connectors/{cid}")
    def connectors_delete(cid: str) -> dict:
        mcpman.save_all([c for c in mcpman.load() if c["id"] != cid])
        if state._mcp:
            state.mcp.drop(cid)
        for a in agent_store.all_agents():
            if cid in a.get("connectors", []):
                agent_store.save(a["id"], {"connectors": [x for x in a["connectors"] if x != cid]})
        return {"ok": True}

    # ---- agent turns and chats --------------------------------------------------------------------------
    def team_hub(team: str):
        def call(method: str, path: str, body: Optional[dict] = None) -> dict:
            p, _, qs = path.partition("?")
            code, data = cloud(state, method, f"/v1/{p}", body, {"team": team, **dict(urllib.parse.parse_qsl(qs))})
            if code >= 400:
                raise RuntimeError(data.get("detail") or f"The hub said {code}")
            return data
        return call

    def llm_step(messages: list, tools: list, tier: str, team: str) -> dict:
        """One model step through the hub; its tokens count toward the team's usage."""
        payload = {"tier": tier, "messages": messages, "tools": tools, "max_tokens": 1800}
        code, data = cloud(state, "POST", "/v1/llm", payload, {"team": team})
        if code == 502 and tier not in ("auto", "super"):  # a pinned tier that can't take tools: Super can
            code, data = cloud(state, "POST", "/v1/llm", {**payload, "tier": "super"}, {"team": team})
        if code != 200:
            raise RuntimeError(data.get("detail") or f"The model said {code}")
        return data

    @app.post("/api/turns")
    def turn_start(body: TurnBody) -> dict:
        chat = (runtime_loop.load_chat(body.chat) if body.chat else {}) or runtime_loop.new_chat(body.agent)
        files = [{"name": str(a.get("name", "file"))[:120], "text": str(a.get("text", ""))[:60_000]} for a in body.attachments]
        turn = runtime_loop.Turn(chat=chat, agent=agent_store.get(body.agent), message=body.message, attachments=files,
                                 mode=body.mode, model=body.model, hub=team_hub(body.team), mcp=state.mcp,
                                 llm=lambda messages, tools, tier: llm_step(messages, tools, tier, body.team),
                                 person=(store.load().get("profile") or {}).get("name") or "you")
        state.turns[turn.id] = turn
        threading.Thread(target=turn.run, daemon=True).start()
        return {"turn": turn.id, "chat": chat["id"]}

    def the_turn(tid: str) -> runtime_loop.Turn:
        t = state.turns.get(tid)
        if not t:
            raise HTTPException(404, "That turn is gone")
        return t

    @app.get("/api/turns/{tid}")
    def turn_events(tid: str, after: int = 0) -> dict:
        t = the_turn(tid)
        return {"events": t.wait(after, 20), "done": t.done}

    @app.post("/api/turns/{tid}/decide")
    def turn_decide(tid: str, body: DecideBody) -> dict:
        the_turn(tid).decide(body.call, body.approve)
        return {"ok": True}

    @app.post("/api/turns/{tid}/run-plan")
    def turn_run_plan(tid: str) -> dict:
        t = the_turn(tid)
        if not t.done or not t.planned:
            raise HTTPException(409, "Nothing planned to run")
        threading.Thread(target=t.run_plan, daemon=True).start()
        return {"ok": True, "after": len(t.events)}

    @app.post("/api/turns/{tid}/cancel")
    def turn_cancel(tid: str) -> dict:
        the_turn(tid).cancel()
        return {"ok": True}

    @app.get("/api/chats")
    def chats_list() -> dict:
        return {"chats": runtime_loop.list_chats()}

    @app.get("/api/chats/{cid}")
    def chats_get(cid: str) -> dict:
        chat = runtime_loop.load_chat(cid) if re.fullmatch(r"[A-Za-z0-9_-]{4,40}", cid) else {}
        if not chat:
            raise HTTPException(404, "No such chat")
        return {k: chat.get(k) for k in ("id", "title", "agent", "view", "updated")}

    @app.delete("/api/chats/{cid}")
    def chats_delete(cid: str) -> dict:
        if re.fullmatch(r"[A-Za-z0-9_-]{4,40}", cid):
            (runtime_loop.chats_dir() / f"{cid}.json").unlink(missing_ok=True)
        return {"ok": True}

    # ---- files (read-only here; agents write through their tools) -----------------------------------------
    def safe(path: str) -> Path:
        try:
            return runtime_tools.resolve(path)
        except PermissionError as e:
            raise HTTPException(403, str(e)) from None

    @app.get("/api/files/roots")
    def files_roots() -> dict:
        return {"roots": [{"name": n, "path": str(p)} for n, p in runtime_tools.roots().items()]}

    @app.get("/api/files/list")
    def files_list(path: str) -> dict:
        d = safe(path)
        if not d.is_dir():
            raise HTTPException(404, "Not a folder")
        items = sorted((p for p in d.iterdir() if p.name not in runtime_tools.SKIP_DIRS),
                       key=lambda p: (not p.is_dir(), p.name.lower()))[:500]
        return {"path": runtime_tools.display(d), "entries": [
            {"name": p.name, "path": runtime_tools.display(p.resolve()), "dir": p.is_dir(),
             "size": p.stat().st_size if p.is_file() else None} for p in items]}

    @app.get("/api/files/read")
    def files_read(path: str) -> dict:
        f = safe(path)
        if not f.is_file():
            raise HTTPException(404, "No such file")
        size = f.stat().st_size
        out = {"path": runtime_tools.display(f), "size": size, "name": f.name}
        if f.suffix.lower() in IMAGES:
            return {**out, "kind": "image", "mime": IMAGES[f.suffix.lower()]}
        if size > 2_000_000:
            return {**out, "kind": "large"}
        try:
            return {**out, "kind": "text", "text": f.read_text(encoding="utf-8")}
        except UnicodeDecodeError:
            return {**out, "kind": "binary"}

    @app.get("/api/files/raw")
    def files_raw(path: str) -> FileResponse:
        f = safe(path)
        if not f.is_file() or f.suffix.lower() not in IMAGES:
            raise HTTPException(404, "Only images are served raw")
        return FileResponse(f, media_type=IMAGES[f.suffix.lower()])

    # ---- browser and terminal ---------------------------------------------------------------------------
    @app.post("/api/browser/window")
    def browser_window(body: UrlBody) -> dict:
        if not body.url.startswith(("http://", "https://")):
            raise HTTPException(400, "Only http and https pages")
        (state.open_window or open_url)(body.url)
        return {"ok": True}

    @app.websocket("/api/terminal")
    async def terminal(ws: WebSocket, k: str = "", cwd: str = "", cols: int = 100, rows: int = 30):
        ours = (f"127.0.0.1:{state.port}", f"localhost:{state.port}")
        origin = ws.headers.get("origin", "")
        if (ws.headers.get("host") not in ours or not secrets.compare_digest(k, state.key)
                or origin not in [f"http://{h}" for h in ours]):
            await ws.close(code=4403)
            return
        try:
            where = runtime_tools.resolve(cwd) if cwd else next(iter(runtime_tools.roots().values()), Path.home())
        except PermissionError:
            where = Path.home()
        if not Path(where).is_dir():  # a connected repo that was moved or deleted
            where = Path.home() if Path.home().is_dir() else Path.cwd()
        await ws.accept()
        pty = terminal_mod.Pty(Path(where), cols, rows)
        loop = asyncio.get_running_loop()

        def pump() -> None:
            try:
                while pty.alive():
                    data = pty.read()
                    if data:
                        asyncio.run_coroutine_threadsafe(ws.send_text(data), loop)
            except (EOFError, OSError):  # the shell exited
                pass
            asyncio.run_coroutine_threadsafe(ws.close(), loop)

        threading.Thread(target=pump, daemon=True).start()
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                if msg.get("t") == "in":
                    pty.write(str(msg.get("d", "")))
                elif msg.get("t") == "resize":
                    pty.resize(int(msg.get("c", 100)), int(msg.get("r", 30)))
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass
        finally:
            pty.kill()

    return app
