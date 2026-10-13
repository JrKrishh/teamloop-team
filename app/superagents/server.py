"""The app's local server. The window's UI talks only to this (same origin, no CORS); this talks to the hub with the
person's session, to Supabase for sign-in, and to the connector on this laptop.

It listens on 127.0.0.1 only. Every /api call must carry the per-launch key the window got in its URL fragment, and
the Host header must be ours, so neither a web page nor a DNS-rebinding trick can drive it.
"""

from __future__ import annotations

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

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, laptop, store, supa

UI = Path(__file__).parent / "ui"
# what the UI may ask the hub for, through /api/cloud/<path>
CLOUD_PATHS = re.compile(r"^(me|teams|board|team|ask|digest|refresh|settings|events"
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
    theme: str = Field(pattern="^(dark|light)$")


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
    @app.api_route("/api/cloud/{path:path}", methods=["GET", "POST", "DELETE"])
    async def to_cloud(path: str, request: Request) -> JSONResponse:
        if not CLOUD_PATHS.match(path):
            raise HTTPException(404, "Not a Super Agents call")
        body = None
        if request.method == "POST":
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
        s["prefs"] = {**(s.get("prefs") or {}), "theme": body.theme}
        store.save(s)
        return s["prefs"]

    return app
