"""TeamLoop cloud hub: Vercel + Supabase. The API shapes match the self-hosted hub (hub/), so the same board page
and the same connector work against both; the differences are who you are (a Supabase sign-in, not a room token)
and where data lives (Postgres, per team). docs/cloud.md.

Env: DATABASE_URL (Supabase transaction pooler), SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, NEBIUS_API_KEY,
PUBLIC_URL (optional; used in invite and sign-in links), HUB_SECURE_COOKIE (default on).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import hub
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from agent_s import agent, llm, progress, qa
from agent_s import digest as agent_digest
from hub import cards
from hub import usage as usage_sum
from hub.relay import _Window
from hub.team import ID_RE, KIND_RE, MAX_EVENT_BYTES, TASK_RE, clean

from . import __version__, auth
from . import blobs as blobstore

STATIC = Path(hub.__file__).parent / "static"
SITE = Path(__file__).parent / "site"
DEMO_FILE = Path(hub.__file__).parent / "demo" / "demo.json"
ACTIVE_SECONDS = 300
DEBOUNCE_SECONDS = 30
RETENTION_DAYS = 30
CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ23456789"  # no vowels: device codes never spell words


# ---- request plumbing -----------------------------------------------------------------------------
class _LazyConn:
    """Connects on first use, so signed-out visitors (the demo) never touch the database: the demo stays up if the
    database is down, and public page views don't spend the pooler's connections."""

    def __init__(self) -> None:
        self.conn: Optional[psycopg.Connection] = None

    def execute(self, *args, **kwargs):
        if self.conn is None:
            self.conn = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, prepare_threshold=None,
                                        connect_timeout=10)
        return self.conn.execute(*args, **kwargs)

    def commit(self) -> None:
        if self.conn is not None:
            self.conn.commit()


def db():
    """One short-lived connection per request: on Vercel any request may land on a fresh instance. Supabase's
    transaction pooler doesn't support prepared statements, hence prepare_threshold=None."""
    lazy = _LazyConn()
    try:
        yield lazy
        lazy.commit()
    except Exception:
        if lazy.conn is not None:
            lazy.conn.rollback()
        raise
    finally:
        if lazy.conn is not None:
            lazy.conn.close()


@dataclass(frozen=True)
class Caller:
    person: Optional[auth.Person]
    kind: str  # "session", "connector" or "anon"
    team_id: Optional[str] = None  # connector tokens are bound to one team


def caller(request: Request, conn=Depends(db), authorization: Optional[str] = Header(default=None)) -> Caller:
    if authorization and authorization.lower().startswith("bearer tl_"):
        h = auth.digest(authorization[7:].strip())
        row = conn.execute(
            "select t.user_id, t.team_id, m.name, m.email from connector_tokens t join memberships m"
            " on m.team_id = t.team_id and m.user_id = t.user_id"
            " where t.token_hash = %s and not t.revoked and m.removed_at is null", (h,)).fetchone()
        if not row:
            raise HTTPException(401, "This connector isn't signed in any more; run `teamloop login` again")
        conn.execute("update connector_tokens set last_used_at = now() where token_hash = %s", (h,))
        return Caller(auth.Person(str(row["user_id"]), row["email"], row["name"]), "connector", str(row["team_id"]))
    # the desktop app sends its session as a bearer token; browsers send the cookie
    bearer = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer s_") else None
    tok = bearer or request.cookies.get(auth.SESSION_COOKIE)
    if tok:
        row = conn.execute("select user_id, email, name from hub_sessions where token_hash = %s and expires_at > now()",
                           (auth.digest(tok),)).fetchone()
        if row:
            return Caller(auth.Person(str(row["user_id"]), row["email"], row["name"]), "session")
    return Caller(None, "anon")


def base_url(request: Request) -> str:
    if os.getenv("PUBLIC_URL"):
        return os.environ["PUBLIC_URL"].rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _uuid_or_400(value: str) -> str:
    import uuid

    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError):
        raise HTTPException(400, "Not a team id") from None


def team_scope(c: Caller, team: Optional[str], conn) -> tuple[str, str, str]:
    """(team_id, team name, role) for a team the caller belongs to, or an HTTP error."""
    if c.kind == "connector":
        team = c.team_id
    elif c.person is None:
        raise HTTPException(401, "Sign in first")
    if not team:
        raise HTTPException(400, "Pick a team")
    team = _uuid_or_400(team)
    row = conn.execute("select m.role, t.name from memberships m join teams t on t.id = m.team_id"
                       " where m.team_id = %s and m.user_id = %s and m.removed_at is null", (team, c.person.id)).fetchone()
    if not row:
        raise HTTPException(403, "You're not in this team")
    return team, row["name"], row["role"]


def lead_scope(c: Caller, team: Optional[str], conn) -> tuple[str, str]:
    team_id, name, role = team_scope(c, team, conn)
    if role != "lead" or c.kind != "session":
        raise HTTPException(403, "Only the team lead can do that")
    return team_id, name


# ---- bodies ---------------------------------------------------------------------------------------
class SessionIn(BaseModel):
    access_token: str = Field(min_length=10, max_length=8192)


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class InviteIn(BaseModel):
    role: str = Field(default="member", pattern="^(lead|member)$")


class RepoLinkIn(BaseModel):
    url: str = Field(min_length=10, max_length=300)


SHARE_DAYS, SHARE_FILES, SHARE_MAX_BYTES, TEAM_SHARE_BYTES = 14, 10, 25 * 1024 * 1024, 300 * 1024 * 1024


class ShareFileIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    size: int = Field(ge=0, le=SHARE_MAX_BYTES)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")


class ShareIn(BaseModel):
    to: Optional[str] = Field(default=None, max_length=120)  # a teammate's name or id; none for the whole team
    note: str = Field(default="", max_length=1000)
    files: list[ShareFileIn] = Field(default_factory=list, max_length=SHARE_FILES)
    repo: Optional[str] = Field(default=None, max_length=300)  # a branch handed over: its repo and branch
    branch: Optional[str] = Field(default=None, max_length=200, pattern=r"^[A-Za-z0-9._/-]+$")


def clean_file_name(name: str) -> str:
    """Just a file's name: never a path, no characters Windows can't keep, no leading dots or spaces."""
    base = re.split(r"[\\/]", name)[-1]
    base = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", base).strip(" .")
    if not base:
        raise HTTPException(400, f"{name!r} isn't a file name")
    return base[:120]


GITHUB_REPO = re.compile(r"^(?:https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100}?)(?:\.git)?/?$")


def github_url(raw: str) -> str:
    """https://github.com/owner/repo for a GitHub repo URL in any of its usual forms, or a 400."""
    m = GITHUB_REPO.match((raw or "").strip())
    if not m:
        raise HTTPException(400, "That isn't a GitHub repo URL (https://github.com/owner/repo)")
    return f"https://github.com/{m.group(1)}/{m.group(2)}"


class EventsIn(BaseModel):
    events: list[dict] = Field(max_length=50)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class DeviceStartIn(BaseModel):
    label: str = Field(default="", max_length=60)


class DeviceApproveIn(BaseModel):
    user_code: str = Field(min_length=9, max_length=9)
    team: str


DATE = r"^\d{4}-\d{2}-\d{2}$"


class TaskIn(BaseModel):
    task: str = Field(default="", max_length=30)
    title: str = Field(min_length=1, max_length=120)
    owner: Optional[str] = Field(default=None, max_length=64)
    due: Optional[str] = Field(default=None, pattern=DATE)


class TaskPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    owner: Optional[str] = Field(default=None, max_length=64)  # "" unassigns
    state: Optional[str] = Field(default=None, pattern="^(open|closed)$")
    due: Optional[str] = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")  # "" clears


class AccessIn(BaseModel):
    mode: str = Field(pattern="^(off|ask|auto)$")
    access: str = Field(default="read", pattern="^(read|edit)$")
    daily_tokens: Optional[int] = Field(default=None, ge=1000, le=100_000_000)  # None: unlimited


class PromptIn(BaseModel):
    session: str = Field(min_length=4, max_length=80)
    prompt: str = Field(min_length=1, max_length=4000)


class DecideIn(BaseModel):
    approve: bool


class FinishIn(BaseModel):
    status: str = Field(pattern="^(done|failed|stopped)$")
    result: str = Field(default="", max_length=12000)
    tokens: int = Field(default=0, ge=0, le=10_000_000_000)
    run_session: Optional[str] = Field(default=None, max_length=80)


class Attachment(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    text: str = Field(max_length=60_000)


class LlmIn(BaseModel):
    tier: str = Field(default="auto", pattern="^(auto|lightning|super|ultra)$")
    effort: Optional[str] = Field(default=None, pattern="^(low|medium|high|max)$")  # None: the provider's own (low)
    messages: list[dict] = Field(min_length=1, max_length=200)
    tools: list[dict] = Field(default_factory=list, max_length=80)
    max_tokens: int = Field(default=2000, ge=16, le=8192)  # thinking counts against it: high effort needs room


class AgentIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    mode: str = Field(default="manual", pattern="^(plan|manual|auto)$")
    model: str = Field(default="auto", pattern="^(auto|lightning|super|ultra)$")
    attachments: list[Attachment] = Field(default_factory=list, max_length=5)


# ---- the app --------------------------------------------------------------------------------------
def create(chat: Optional[Callable] = None, chat_step: Optional[Callable] = None, blobs=None) -> FastAPI:
    chat = chat or llm.chat_json
    chat_step = chat_step or llm.chat_tools
    store = blobs if blobs is not None else blobstore.from_env()  # where shared files live (blobs.py)
    app = FastAPI(title="TeamLoop cloud", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    posts = _Window(60, 60.0)
    asks = _Window(30, 600.0)
    llm_steps = _Window(150, 600.0)  # an agent turn is a few steps; this allows a busy person, not a script
    digests: dict[str, tuple[float, dict]] = {}
    failed: dict[tuple[str, str], float] = {}
    demo = _Demo()

    import mimetypes

    mimetypes.add_type("image/webp", ".webp")
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # The website is the landing page and invite links; the product is the Super Agents app. /auth and /device stay
    # for `teamloop login` from a terminal (the device flow signs in on the web).
    app.mount("/site", StaticFiles(directory=SITE), name="site")
    # the phone remote (an installable web app): pairs from a QR code in the Super Agents app, then talks to the laptop
    # end to end encrypted through the relay below (or Supabase Realtime)
    app.mount("/remote", StaticFiles(directory=SITE / "remote", html=True), name="remote")

    def landing() -> FileResponse:
        return FileResponse(SITE / "index.html")

    def invite_page(token: str) -> FileResponse:
        return FileResponse(SITE / "join.html")

    def page() -> FileResponse:
        return FileResponse(STATIC / "board.html")

    app.add_api_route("/", landing, include_in_schema=False)
    app.add_api_route("/join/{token}", invite_page, include_in_schema=False)
    for path in ("/auth", "/device"):
        app.add_api_route(path, page, include_in_schema=False)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "version": __version__, "mode": "cloud"}

    @app.get("/v1/config")
    def config() -> dict:
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_PUBLISHABLE_KEY")
        # the phone remote's relay: Supabase Realtime when there's Supabase; else this hub's own socket (not on
        # Vercel: its instances don't share the rooms below)
        relay = "supabase" if url and key else None if os.environ.get("VERCEL") else "hub"
        return {"mode": "cloud", "supabase_url": url, "supabase_key": key, "relay": relay}

    rooms: dict[str, set] = {}

    @app.websocket("/v1/relay")
    async def relay(ws: WebSocket) -> None:
        """The phone remote's relay for development and self-hosting: the part of Supabase Realtime's protocol it
        uses (join a channel, broadcast to the others on it, heartbeat). Messages are sealed end to end; this only
        passes them on, to whoever joined the channel, and keeps nothing."""
        await ws.accept()
        joined: set[str] = set()

        async def reply(topic: str, ref) -> None:
            await ws.send_text(json.dumps({"topic": topic, "event": "phx_reply", "payload": {"status": "ok", "response": {}}, "ref": ref}))
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > 1_000_000:
                    break
                m = json.loads(raw)
                topic, event = m.get("topic"), m.get("event")
                if event == "phx_join" and isinstance(topic, str) and topic.startswith("realtime:") and len(topic) <= 80:
                    rooms.setdefault(topic, set()).add(ws)
                    joined.add(topic)
                    await reply(topic, m.get("ref"))
                elif event == "heartbeat":
                    await reply("phoenix", m.get("ref"))
                elif event == "broadcast" and topic in joined:
                    out = json.dumps({"topic": topic, "event": "broadcast", "payload": m.get("payload")})
                    for peer in list(rooms.get(topic, ())):
                        if peer is not ws:
                            try:
                                await peer.send_text(out)
                            except Exception:  # noqa: BLE001 - that peer left
                                rooms[topic].discard(peer)
        except Exception:  # noqa: BLE001 - closed, or not JSON
            pass
        finally:
            for t in joined:
                rooms.get(t, set()).discard(ws)
                if not rooms.get(t):
                    rooms.pop(t, None)

    # ---- sign-in -----------------------------------------------------------------------------------
    def new_session(body: SessionIn, conn) -> tuple[str, auth.Person]:
        """Trade a Supabase access token (from GitHub or email/password sign-in) for a hub session."""
        try:
            person = auth.supabase_user(body.access_token)
        except PermissionError as e:
            raise HTTPException(401, str(e)) from None
        tok = auth.new_token("s_")
        conn.execute("insert into hub_sessions (token_hash, user_id, email, name, expires_at) values (%s, %s, %s, %s, %s)",
                     (auth.digest(tok), person.id, person.email, person.name,
                      datetime.now(timezone.utc) + timedelta(days=auth.SESSION_DAYS)))
        return tok, person

    @app.post("/v1/session")
    def session(body: SessionIn, response: Response, conn=Depends(db)) -> dict:
        tok, person = new_session(body, conn)
        response.set_cookie(auth.SESSION_COOKIE, tok, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                            secure=os.getenv("HUB_SECURE_COOKIE", "1") != "0")
        return {"user": {"id": person.id, "email": person.email, "name": person.name}}

    @app.post("/v1/app/session")
    def app_session(body: SessionIn, conn=Depends(db)) -> dict:
        """The desktop app's sign-in: the same session, handed back as a bearer token instead of a cookie."""
        tok, person = new_session(body, conn)
        return {"token": tok, "expires_in": auth.SESSION_DAYS * 86400,
                "user": {"id": person.id, "email": person.email, "name": person.name}}

    @app.post("/v1/logout")
    def logout(request: Request, response: Response, conn=Depends(db),
               authorization: Optional[str] = Header(default=None)) -> dict:
        bearer = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer s_") else None
        tok = bearer or request.cookies.get(auth.SESSION_COOKIE)
        if tok:
            conn.execute("delete from hub_sessions where token_hash = %s", (auth.digest(tok),))
        response.delete_cookie(auth.SESSION_COOKIE)
        return {"ok": True}

    @app.get("/v1/me")
    def me(c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        if c.person is None:
            return {"user": None, "role": "viewer", "demo": True, "teams": []}
        user = {"id": c.person.id, "email": c.person.email, "name": c.person.name}
        rows = conn.execute("select t.id, t.name, m.role from memberships m join teams t on t.id = m.team_id"
                            " where m.user_id = %s and m.removed_at is null order by t.created_at", (c.person.id,)).fetchall()
        teams = [{"id": str(r["id"]), "name": r["name"], "role": r["role"]} for r in rows]
        if c.kind == "connector":
            t = next((t for t in teams if t["id"] == c.team_id), None)
            return {"user": user, "team": t, "role": t["role"] if t else None, "demo": False}
        return {"user": user, "teams": teams, "demo": False}

    # ---- teams, invites, members -------------------------------------------------------------------
    @app.post("/v1/teams")
    def create_team(body: TeamIn, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        if c.kind != "session":
            raise HTTPException(401, "Sign in first")
        row = conn.execute("insert into teams (name, created_by) values (%s, %s) returning id",
                           (body.name.strip(), c.person.id)).fetchone()
        conn.execute("insert into memberships (team_id, user_id, email, name, role) values (%s, %s, %s, %s, 'lead')",
                     (row["id"], c.person.id, c.person.email, c.person.name))
        return {"id": str(row["id"]), "name": body.name.strip(), "role": "lead"}

    @app.post("/v1/teams/{team}/invites")
    def make_invite(team: str, body: InviteIn, request: Request, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, name = lead_scope(c, team, conn)
        tok = auth.new_token("inv_")
        expires = datetime.now(timezone.utc) + timedelta(days=7)
        conn.execute("insert into invites (token_hash, team_id, role, created_by, expires_at) values (%s, %s, %s, %s, %s)",
                     (auth.digest(tok), team_id, body.role, c.person.id, expires))
        return {"url": f"{base_url(request)}/join/{tok}", "team": name, "role": body.role, "expires_at": expires.isoformat()}

    def _invite(conn, tok: str) -> Optional[dict]:
        return conn.execute(
            "select i.team_id, i.role, t.name from invites i join teams t on t.id = i.team_id where i.token_hash = %s"
            " and not i.revoked and i.expires_at > now() and i.uses < i.max_uses", (auth.digest(tok),)).fetchone()

    @app.get("/v1/invites/{tok}")
    def invite_info(tok: str, conn=Depends(db)) -> dict:
        inv = _invite(conn, tok)
        if not inv:
            return {"valid": False, "team": None, "team_id": None, "role": None}
        return {"valid": True, "team": inv["name"], "team_id": str(inv["team_id"]), "role": inv["role"]}

    @app.post("/v1/invites/{tok}/accept")
    def accept_invite(tok: str, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        if c.kind != "session":
            raise HTTPException(401, "Sign in first")
        inv = _invite(conn, tok)
        if not inv:
            raise HTTPException(404, "This invite link has expired or was used up; ask your lead for a new one")
        have = conn.execute("select role, removed_at from memberships where team_id = %s and user_id = %s",
                            (inv["team_id"], c.person.id)).fetchone()
        if have and have["removed_at"]:
            raise HTTPException(403, "The lead removed you from this team; ask them to restore you")
        if not have:
            conn.execute("insert into memberships (team_id, user_id, email, name, role) values (%s, %s, %s, %s, %s)",
                         (inv["team_id"], c.person.id, c.person.email, c.person.name, inv["role"]))
            conn.execute("update invites set uses = uses + 1 where token_hash = %s", (auth.digest(tok),))
        return {"team": {"id": str(inv["team_id"]), "name": inv["name"]}, "role": have["role"] if have else inv["role"]}

    @app.delete("/v1/teams/{team}/members/{user_id}")
    def remove_member(team: str, user_id: str, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, _ = lead_scope(c, team, conn)
        user_id = _uuid_or_400(user_id)
        if user_id == c.person.id:
            raise HTTPException(400, "You can't remove yourself")
        gone = conn.execute("update memberships set removed_at = now() where team_id = %s and user_id = %s"
                            " and removed_at is null", (team_id, user_id)).rowcount
        if not gone:
            raise HTTPException(404, "No such member")
        conn.execute("update connector_tokens set revoked = true where team_id = %s and user_id = %s", (team_id, user_id))
        return {"ok": True}

    @app.post("/v1/teams/{team}/members/{user_id}/restore")
    def restore_member(team: str, user_id: str, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, _ = lead_scope(c, team, conn)
        back = conn.execute("update memberships set removed_at = null where team_id = %s and user_id = %s"
                            " and removed_at is not null", (team_id, _uuid_or_400(user_id))).rowcount
        if not back:
            raise HTTPException(404, "That member isn't removed")
        return {"ok": True}

    # ---- the team's GitHub repos: a teammate's app clones one into a folder they pick (Get the project) ----------
    def repos_of(conn, team_id: str, role: str, c: Caller) -> dict:
        rows = conn.execute("select url from team_repos where team_id = %s order by added_at", (team_id,)).fetchall()
        return {"repos": [{"url": r["url"], "name": r["url"].removeprefix("https://github.com/")} for r in rows],
                "can_edit": role == "lead" and c.kind == "session"}

    @app.get("/v1/teams/{team}/repos")
    def team_repos(team: str, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, _, role = team_scope(c, team, conn)
        return repos_of(conn, team_id, role, c)

    @app.post("/v1/teams/{team}/repos")
    def add_team_repo(team: str, body: RepoLinkIn, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, _ = lead_scope(c, team, conn)
        if conn.execute("select count(*) as n from team_repos where team_id = %s", (team_id,)).fetchone()["n"] >= 20:
            raise HTTPException(400, "A team can link up to 20 repos")
        conn.execute("insert into team_repos (team_id, url, added_by) values (%s, %s, %s) on conflict do nothing",
                     (team_id, github_url(body.url), c.person.id))
        return repos_of(conn, team_id, "lead", c)

    @app.delete("/v1/teams/{team}/repos")
    def remove_team_repo(team: str, url: str, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, _ = lead_scope(c, team, conn)
        conn.execute("delete from team_repos where team_id = %s and url = %s", (team_id, github_url(url)))
        return repos_of(conn, team_id, "lead", c)

    # ---- Super Team → Files: files and branches teammates share ---------------------------------------
    # The record (who shared what with whom, who saved it) is the team's, like prompts: the lead sees it all. The
    # files are only for the sender and the people they were shared with, through 5-minute links, for 14 days.
    def share_view(r: dict, me: str) -> dict:
        to = str(r["to_user"]) if r["to_user"] else None
        return {"id": str(r["id"]), "kind": r["kind"], "from": {"id": str(r["from_user"]), "name": r["from_name"]},
                "to": {"id": to, "name": r["to_name"]} if to else None, "note": r["note"], "repo": r["repo"], "branch": r["branch"],
                "files": [{"n": i, "name": f["name"], "size": f["size"]} for i, f in enumerate(r["files"])],
                "status": r["status"], "saved_by": r["saved_by"], "created_at": r["created_at"].timestamp(),
                "expires_at": r["expires_at"].timestamp(), "mine": str(r["from_user"]) == me,
                "for_me": to == me or (to is None and str(r["from_user"]) != me),
                "can_get": str(r["from_user"]) == me or to in (None, me)}

    def visible_share(conn, team_id: str, role: str, sid: str, me: str) -> dict:
        r = conn.execute("select * from shares where team_id = %s and id = %s", (team_id, _uuid_or_400(sid))).fetchone()
        if not r or (role != "lead" and me not in (str(r["from_user"]), str(r["to_user"])) and r["to_user"] is not None):
            raise HTTPException(404, "No such share")
        return r

    def sweep_shares(conn, team_id: str) -> None:
        """No cron on Vercel Hobby: shares past their 14 days lose their files when someone next lists them."""
        gone = conn.execute("update shares set status = 'expired' where team_id = %s and status in ('uploading', 'ready')"
                            " and expires_at < now() returning files", (team_id,)).fetchall()
        paths = [f["path"] for r in gone for f in r["files"]]
        if paths and store:
            try:
                store.delete(paths)
            except (OSError, urllib.error.URLError):
                pass  # the bucket's own lifetime rules are the backstop

    @app.post("/v1/shares")
    def create_share(body: ShareIn, request: Request, team: Optional[str] = None, c: Caller = Depends(caller),
                     conn=Depends(db)) -> dict:
        team_id, _, _ = team_scope(c, team, conn)
        if c.kind != "session":
            raise HTTPException(401, "Sign in first")
        if bool(body.files) == bool(body.branch):
            raise HTTPException(400, "Share files, or a branch")
        if body.files and not store:
            raise HTTPException(503, "File sharing isn't set up on this hub yet (it needs SUPABASE_SECRET_KEY)")
        to = None
        if body.to:
            who = body.to.strip()
            to = conn.execute("select user_id, name from memberships where team_id = %s and removed_at is null and"
                              " (user_id::text = %s or lower(name) = lower(%s))", (team_id, who, who)).fetchone()
            if not to or str(to["user_id"]) == c.person.id:
                raise HTTPException(400, f"{who} isn't a teammate here")
        names = [clean_file_name(f.name) for f in body.files]
        if len(set(n.lower() for n in names)) != len(names):
            raise HTTPException(400, "Two files have the same name")
        size = sum(f.size for f in body.files)
        if body.files:
            sweep_shares(conn, team_id)
            held = conn.execute("select coalesce(sum((f->>'size')::bigint), 0) as n from shares, jsonb_array_elements(files) f"
                                " where team_id = %s and status in ('uploading', 'ready')", (team_id,)).fetchone()["n"]
            if held + size > TEAM_SHARE_BYTES:
                raise HTTPException(400, f"The team's shared files would pass {TEAM_SHARE_BYTES // 2**20} MB; delete some first")
        sid = conn.execute("select gen_random_uuid() as id").fetchone()["id"]
        files = [{"name": n, "size": f.size, "sha256": f.sha256, "path": f"{team_id}/{sid}/{i}-{n}"}
                 for i, (n, f) in enumerate(zip(names, body.files))]
        r = conn.execute("insert into shares (id, team_id, from_user, from_name, to_user, to_name, kind, note, files, repo,"
                         " branch, status, expires_at) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now() + make_interval(days => %s))"
                         " returning *", (sid, team_id, c.person.id, c.person.name, to["user_id"] if to else None,
                                          to["name"] if to else None, "files" if body.files else "branch", body.note.strip(),
                                          Jsonb(files), body.repo, body.branch, "uploading" if body.files else "ready",
                                          SHARE_DAYS)).fetchone()
        uploads = [{"name": f["name"], **store.upload(f["path"], f["size"], base_url(request))} for f in files] if files else []
        return {**share_view(r, c.person.id), "uploads": uploads}

    @app.post("/v1/shares/{sid}/ready")
    def share_ready(sid: str, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        """The sender's app uploaded every file: check each arrived whole, then teammates see the share."""
        team_id, _, role = team_scope(c, team, conn)
        r = visible_share(conn, team_id, role, sid, c.person.id)
        if str(r["from_user"]) != c.person.id or r["status"] != "uploading":
            raise HTTPException(409, "That share isn't waiting for its files")
        for f in r["files"]:
            if store.size(f["path"]) != f["size"]:
                raise HTTPException(400, f"{f['name']} didn't arrive whole; share it again")
        r = conn.execute("update shares set status = 'ready' where id = %s returning *", (r["id"],)).fetchone()
        return share_view(r, c.person.id)

    @app.get("/v1/shares")
    def list_shares(team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, _, role = team_scope(c, team, conn)
        me = c.person.id
        sweep_shares(conn, team_id)
        mine = "" if role == "lead" else " and (from_user = %s or to_user = %s or to_user is null)"
        rows = conn.execute(f"select * from shares where team_id = %s and status <> 'deleted'"
                            f" and (status <> 'uploading' or from_user = %s){mine} order by created_at desc limit 100",
                            (team_id, me) if role == "lead" else (team_id, me, me, me)).fetchall()
        return {"shares": [share_view(r, me) for r in rows], "role": role}

    @app.get("/v1/shares/{sid}")
    def one_share(sid: str, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, _, role = team_scope(c, team, conn)
        return share_view(visible_share(conn, team_id, role, sid, c.person.id), c.person.id)

    @app.get("/v1/shares/{sid}/files/{n}")
    def share_file(sid: str, n: int, request: Request, team: Optional[str] = None, c: Caller = Depends(caller),
                   conn=Depends(db)) -> dict:
        """A 5-minute link to one file, for the sender and the people it was shared with; who saved it goes on record."""
        team_id, _, role = team_scope(c, team, conn)
        r = visible_share(conn, team_id, role, sid, c.person.id)
        if not share_view(r, c.person.id)["can_get"]:
            raise HTTPException(403, "This share is between two teammates; you see the record, not the files")
        if r["status"] != "ready" or not 0 <= n < len(r["files"]):
            raise HTTPException(410 if r["status"] == "expired" else 404, "That file isn't there any more")
        f = r["files"][n]
        if str(r["from_user"]) != c.person.id:
            conn.execute("update shares set saved_by = saved_by || to_jsonb(%s::text) where id = %s and not saved_by ? %s",
                         (c.person.name, r["id"], c.person.name))
        return {"url": store.download(f["path"], 300, base_url(request)), "name": f["name"], "size": f["size"], "sha256": f["sha256"]}

    @app.delete("/v1/shares/{sid}")
    def delete_share(sid: str, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, _, role = team_scope(c, team, conn)
        r = visible_share(conn, team_id, role, sid, c.person.id)
        if str(r["from_user"]) != c.person.id and role != "lead":
            raise HTTPException(403, "Only who shared it, or the lead, can delete it")
        conn.execute("update shares set status = 'deleted' where id = %s", (r["id"],))
        if r["files"] and store:
            store.delete([f["path"] for f in r["files"]])
        return {"ok": True}

    @app.put("/v1/blobs/{token}")
    async def put_blob(token: str, request: Request) -> dict:
        if not isinstance(store, blobstore.LocalBlobs):
            raise HTTPException(404, "Not here")
        try:
            f = store.check(token, "put")
        except (PermissionError, ValueError) as e:
            raise HTTPException(403, str(e)) from None
        data = await request.body()
        if len(data) > SHARE_MAX_BYTES:
            raise HTTPException(413, "Over 25 MB")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        return {"ok": True}

    @app.get("/v1/blobs/{token}")
    def get_blob(token: str) -> FileResponse:
        if not isinstance(store, blobstore.LocalBlobs):
            raise HTTPException(404, "Not here")
        try:
            f = store.check(token, "get")
        except (PermissionError, ValueError) as e:
            raise HTTPException(403, str(e)) from None
        if not f.is_file():
            raise HTTPException(404, "That file isn't there any more")
        return FileResponse(f, media_type="application/octet-stream")

    @app.get("/v1/settings")
    def settings(team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, name = lead_scope(c, team, conn)
        n = conn.execute("select count(*) as n from memberships where team_id = %s and removed_at is null", (team_id,)).fetchone()
        return {"room": name, "members": n["n"], "agent_s_model": llm.model_for("progress"), "lead_key_set": True,
                "github_repos": [], "github_secret_set": False, "notify_webhook_set": False, "retention_days": RETENTION_DAYS,
                "posts_per_minute": 60}

    # ---- `teamloop login`: device sign-in ----------------------------------------------------------
    @app.post("/v1/device/start")
    def device_start(body: DeviceStartIn, request: Request, conn=Depends(db)) -> dict:
        dev = secrets.token_urlsafe(32)
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        code = f"{code[:4]}-{code[4:]}"
        conn.execute("insert into devices (device_hash, user_code, expires_at) values (%s, %s, %s)",
                     (auth.digest(dev), code, datetime.now(timezone.utc) + timedelta(minutes=15)))
        return {"device_code": dev, "user_code": code, "verify_url": f"{base_url(request)}/device?code={code}",
                "interval": 3, "expires_in": 900}

    @app.get("/v1/device/poll")
    def device_poll(device_code: str, request: Request, conn=Depends(db)) -> dict:
        row = conn.execute("select d.status, d.token, d.team_id, d.user_id, d.expires_at < now() as expired, t.name as team,"
                           " m.name from devices d left join teams t on t.id = d.team_id left join memberships m"
                           " on m.team_id = d.team_id and m.user_id = d.user_id where d.device_hash = %s",
                           (auth.digest(device_code),)).fetchone()
        if not row:
            raise HTTPException(404, "Unknown device code")
        if row["status"] == "approved" and row["token"]:
            conn.execute("update devices set status = 'claimed', token = null where device_hash = %s", (auth.digest(device_code),))
            return {"status": "approved", "token": row["token"], "team": {"id": str(row["team_id"]), "name": row["team"]},
                    "name": row["name"], "url": base_url(request)}
        if row["expired"] and row["status"] == "pending":
            return {"status": "expired"}
        return {"status": row["status"]}

    @app.get("/v1/device/{user_code}")
    def device_info(user_code: str, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        row = conn.execute("select status, expires_at > now() as live from devices where user_code = %s", (user_code.upper(),)).fetchone()
        return {"valid": bool(row and row["live"] and row["status"] == "pending")}

    @app.post("/v1/device/approve")
    def device_approve(body: DeviceApproveIn, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        if c.kind != "session":
            raise HTTPException(401, "Sign in first")
        team_id, name, _ = team_scope(c, body.team, conn)
        tok = auth.new_token("tl_")
        done = conn.execute("update devices set status = 'approved', token = %s, user_id = %s, team_id = %s"
                            " where user_code = %s and status = 'pending' and expires_at > now()",
                            (tok, c.person.id, team_id, body.user_code.upper())).rowcount
        if not done:
            raise HTTPException(404, "That code has expired or was already used; run `teamloop login` again")
        conn.execute("insert into connector_tokens (token_hash, user_id, team_id, label) values (%s, %s, %s, %s)",
                     (auth.digest(tok), c.person.id, team_id, f"teamloop, approved {time.strftime('%Y-%m-%d')}"))
        return {"ok": True, "team": name}

    @app.post("/v1/teams/{team}/connector")
    def connector_token(team: str, body: DeviceStartIn, request: Request, c: Caller = Depends(caller),
                        conn=Depends(db)) -> dict:
        """The desktop app connects its laptop to a team in one step: a connector token for this person and team,
        the same kind `teamloop login` gets, for the hooks and the MCP server on this machine."""
        if c.kind != "session":
            raise HTTPException(401, "Sign in first")
        team_id, name, _ = team_scope(c, team, conn)
        tok = auth.new_token("tl_")
        conn.execute("insert into connector_tokens (token_hash, user_id, team_id, label) values (%s, %s, %s, %s)",
                     (auth.digest(tok), c.person.id, team_id, f"{body.label or 'Super Agents app'}, {time.strftime('%Y-%m-%d')}"))
        return {"token": tok, "team": {"id": team_id, "name": name}, "name": c.person.name, "url": base_url(request)}

    # ---- events in (connector) ---------------------------------------------------------------------
    @app.post("/v1/events")
    def post_events(body: EventsIn, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        if c.kind != "connector":
            raise HTTPException(401, "Events come from a signed-in connector (`teamloop login`)")
        if not posts.allow(f"{c.team_id}\0{c.person.id}", time.time()):
            raise HTTPException(429, "Too many event batches; the connector will retry")
        rows = []
        for e in body.events:
            if "local" in e:
                raise HTTPException(400, "Events must not carry 'local': that text never leaves the laptop")
            if not ID_RE.match(str(e.get("id", ""))) or not KIND_RE.match(str(e.get("kind", ""))):
                raise HTTPException(422, "Each event needs a 32-hex id and a lowercase kind")
            task = e.get("task") if TASK_RE.match(str(e.get("task") or "")) else None
            e = {**clean(e), "member": c.person.name, "task": task}
            if len(json.dumps(e, ensure_ascii=False).encode()) > MAX_EVENT_BYTES:
                raise HTTPException(413, f"An event is over {MAX_EVENT_BYTES} bytes")
            rows.append((c.team_id, e["id"], c.person.id, c.person.name, task, e["kind"], str(e.get("ts", ""))[:32], Jsonb(e)))
        new = 0
        for r in rows:
            new += conn.execute("insert into events (team_id, id, user_id, member, task, kind, ts, body)"
                                " values (%s, %s, %s, %s, %s, %s, %s, %s) on conflict do nothing", r).rowcount
        if secrets.randbelow(50) == 0:  # no cron on Vercel Hobby: every ~50th batch sweeps what's past retention
            conn.execute("delete from events where team_id = %s and received_at < now() - make_interval(days => %s)",
                         (c.team_id, RETENTION_DAYS))
            conn.execute("delete from snapshots where team_id = %s and created_at < now() - make_interval(days => %s)",
                         (c.team_id, RETENTION_DAYS))
            conn.execute("delete from agent_usage where team_id = %s and at < now() - make_interval(days => %s)",
                         (c.team_id, RETENTION_DAYS))
            conn.execute("delete from session_prompts where team_id = %s and created_at < now() - make_interval(days => %s)",
                         (c.team_id, RETENTION_DAYS))
            conn.execute("delete from shares where team_id = %s and status in ('expired', 'deleted')"
                         " and created_at < now() - make_interval(days => %s)", (c.team_id, RETENTION_DAYS))
            conn.execute("delete from hub_sessions where expires_at < now()")
            conn.execute("delete from devices where expires_at < now() - interval '1 day'")
        return {"accepted": new, "duplicates": len(rows) - new}

    # ---- usage: Super Agents' own model calls, per team and person ------------------------------------
    def record_usage(conn, team_id: str, person: Optional[auth.Person], source: str, used: dict) -> None:
        if used.get("calls"):
            conn.execute("insert into agent_usage (team_id, user_id, member, source, model, calls, tokens_in, tokens_out)"
                         " values (%s, %s, %s, %s, %s, %s, %s, %s)",
                         (team_id, person.id if person else None, person.name if person else None, source,
                          str(used.get("model") or "")[:80], int(used["calls"]), int(used.get("in") or 0), int(used.get("out") or 0)))

    # ---- reads -------------------------------------------------------------------------------------
    def task_events(conn, team_id: str, task: Optional[str] = None, limit: int = 400) -> list[dict]:
        sql = "select body from events where team_id = %s" + (" and task = %s" if task else "") + " order by ts desc limit %s"
        rows = conn.execute(sql, (team_id, task, limit) if task else (team_id, limit)).fetchall()
        return [r["body"] for r in reversed(rows)]

    def refresh_progress(conn, team_id: str, budget: float = 20.0, limit: int = 2) -> int:
        """No background workers on Vercel: the open board asks for this (POST /v1/refresh) after it renders, and
        Agent S re-estimates at most `limit` stale tasks within `budget` seconds. One refresh per team at a time."""
        if not conn.execute("select pg_try_advisory_xact_lock(hashtext(%s)) as ok", (team_id,)).fetchone()["ok"]:
            return 0
        made = 0
        due = conn.execute(
            "select e.task, max(e.received_at) as last from events e where e.team_id = %s and e.task is not null"
            " group by e.task having max(e.received_at) < now() - make_interval(secs => %s) and max(e.received_at) >"
            " coalesce((select max(s.created_at) from snapshots s where s.team_id = %s and s.task = e.task),"
            " 'epoch'::timestamptz) order by last desc limit %s", (team_id, DEBOUNCE_SECONDS, team_id, limit)).fetchall()
        start = time.time()
        with llm.meter() as used:
            for row in due:
                key = (team_id, row["task"])
                if time.time() - start > budget or time.time() - failed.get(key, 0) < 60:
                    continue
                evs = task_events(conn, team_id, row["task"])
                try:
                    snap = progress.estimate(row["task"], evs, cards.title_for(row["task"], evs), chat=chat)
                except Exception:  # noqa: BLE001 - try again in a minute
                    failed[key] = time.time()
                    continue
                conn.execute("insert into snapshots (team_id, task, created_at, body) values (%s, %s, greatest(now(), %s), %s)",
                             (team_id, row["task"], row["last"], Jsonb(snap)))
                made += 1
        record_usage(conn, team_id, None, "progress", used)
        conn.commit()
        return made

    def planned(conn, team_id: str) -> dict[str, dict]:
        return {r["task"]: r for r in conn.execute(
            "select task, title, owner_name, state, to_char(due, 'YYYY-MM-DD') as due, extract(epoch from created_at) as at"
            " from tasks where team_id = %s", (team_id,))}

    def build_board(conn, team_id: str, team_name: str) -> dict:
        now = time.time()
        tasks = conn.execute("select task, extract(epoch from max(received_at)) as last, count(*) as n from events"
                             " where team_id = %s and task is not null group by task order by last desc limit 60",
                             (team_id,)).fetchall()
        snaps = {r["task"]: r["body"] for r in conn.execute(
            "select distinct on (task) task, body from snapshots where team_id = %s order by task, created_at desc", (team_id,))}
        plan = planned(conn, team_id)
        spent = {r["task"]: {"tokens": int(r["tokens"] or 0), "turns": int(r["turns"])} for r in conn.execute(
            "select task, count(*) as turns, sum(coalesce((u->>'in')::bigint, 0) + coalesce((u->>'cw')::bigint, 0)"
            " + coalesce((u->>'out')::bigint, 0)) as tokens from (select task, body->'facts'->'usage' as u from events"
            " where team_id = %s and kind = 'turn_end' and task is not null) x where u is not null group by task", (team_id,))}
        out = []
        for t in tasks:  # tasks with session events: live progress; a plan adds its owner, and closing marks it done
            card = cards.card(t["task"], task_events(conn, team_id, t["task"], 200), snaps.get(t["task"]), float(t["last"]), t["n"])
            card["usage"] = spent.get(t["task"])
            p = plan.pop(t["task"], None)
            card["owner"] = p["owner_name"] if p else None
            card["due"] = p["due"] if p else None
            if p:  # a name the team gave it (a rename) beats the session's; a task id stored as a title isn't a name
                card["title"] = (p["title"] if p["title"] != t["task"] else "") or card["title"]
                if p["state"] == "closed":
                    card["status"] = "done"
            out.append(card)
        for p in sorted(plan.values(), key=lambda p: p["at"]):  # planned, no session yet
            if p["state"] == "open":
                out.append({"task": p["task"], "title": p["title"], "events": 0, "owner": p["owner_name"],
                            "members": [p["owner_name"]] if p["owner_name"] else [], "tools": [], "pr": None,
                            "last_activity": float(p["at"]), "status": "todo", "progress": None, "recent": [], "usage": None,
                            "due": p["due"]})
        people = conn.execute(
            "select m.name, extract(epoch from max(e.received_at)) as last from memberships m left join events e"
            " on e.team_id = m.team_id and e.user_id = m.user_id where m.team_id = %s and m.removed_at is null"
            " group by m.name", (team_id,)).fetchall()
        return {"room": team_name, "generated_at": now, "tasks": out, "demo": False,
                "members": [{"name": p["name"], "last_activity": float(p["last"] or 0),
                             "active": bool(p["last"]) and now - float(p["last"]) < ACTIVE_SECONDS} for p in people]}

    @app.get("/v1/board")
    def board(team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        if team == "demo" or (c.kind == "anon" and not team):
            return demo.board()
        team_id, name, role = team_scope(c, team, conn)
        return {**build_board(conn, team_id, name), "role": role}

    @app.post("/v1/refresh")
    def refresh(team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        if team == "demo" or (c.kind == "anon" and not team):
            return {"updated": 0}
        return {"updated": refresh_progress(conn, team_scope(c, team, conn)[0])}

    @app.get("/v1/tasks/{task}")
    def task_detail(task: str, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        if not TASK_RE.match(task):
            raise HTTPException(400, "Not a task id")
        if team == "demo" or (c.kind == "anon" and not team):
            return demo.task(task)
        team_id, name, _ = team_scope(c, team, conn)
        evs = task_events(conn, team_id, task)
        if not evs:
            p = planned(conn, team_id).get(task)
            if not p:
                raise HTTPException(404, "No activity for this task")
            return {"task": task, "title": p["title"], "status": "todo" if p["state"] == "open" else "done", "pr": None,
                    "members": [p["owner_name"]] if p["owner_name"] else [], "tools": [], "progress": None,
                    "owner": p["owner_name"], "due": p["due"], "history": [], "timeline": []}
        history = conn.execute("select extract(epoch from created_at) as at, body from snapshots where team_id = %s and task = %s"
                               " order by created_at desc limit 20", (team_id, task)).fetchall()
        card = next((t for t in build_board(conn, team_id, name)["tasks"] if t["task"] == task), {})
        return {**{k: card.get(k) for k in ("task", "title", "status", "pr", "members", "tools", "progress", "usage", "due", "owner")},
                "history": [{"at": float(h["at"]), "percent": h["body"].get("percent"), "agent_says": h["body"].get("agent_says_percent")}
                            for h in reversed(history)],
                "timeline": cards.timeline(evs)}

    # ---- planning: tasks on the board before any session reports on them -----------------------------
    def member_named(conn, team_id: str, name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        if not name:
            return None, None
        row = conn.execute("select user_id, name from memberships where team_id = %s and removed_at is null"
                           " and lower(name) = lower(%s) limit 1", (team_id, name.strip())).fetchone()
        if not row:
            raise HTTPException(400, f"{name} isn't in this team")
        return str(row["user_id"]), row["name"]

    def task_ids(conn, team_id: str) -> set[str]:
        rows = conn.execute("select distinct task from events where team_id = %s and task is not null"
                            " union select task from tasks where team_id = %s", (team_id, team_id)).fetchall()
        return {r["task"] for r in rows}

    @app.post("/v1/tasks")
    def create_task(body: TaskIn, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        if c.kind != "session":
            raise HTTPException(401, "Sign in first")
        team_id, name, _ = team_scope(c, team, conn)
        title = " ".join(body.title.split())
        same = next((t["task"] for t in build_board(conn, team_id, name)["tasks"]
                     if t["status"] != "done" and " ".join((t["title"] or "").split()).lower() == title.lower()), None)
        if same:  # asking an agent twice shouldn't put the same work on the board twice
            raise HTTPException(409, f"{same} is already on the board with that title. Use {same}, or give the new task a different title.")
        have = task_ids(conn, team_id)
        task = body.task.strip().upper()
        if not TASK_RE.match(task) or task in have:
            task = agent.next_id(have)
        owner_id, owner = member_named(conn, team_id, body.owner)
        conn.execute("insert into tasks (team_id, task, title, owner_id, owner_name, created_by, due)"
                     " values (%s, %s, %s, %s, %s, %s, %s)", (team_id, task, body.title.strip(), owner_id, owner, c.person.id, body.due))
        return {"task": task, "title": body.title.strip(), "owner": owner, "state": "open", "due": body.due}

    @app.patch("/v1/tasks/{task}")
    def update_task(task: str, body: TaskPatch, team: Optional[str] = None, c: Caller = Depends(caller),
                    conn=Depends(db)) -> dict:
        """Assign, rename, close or reopen. A task that only has session events gets a plan row here."""
        if c.kind != "session":
            raise HTTPException(401, "Sign in first")
        team_id, name, _ = team_scope(c, team, conn)
        if task not in task_ids(conn, team_id):
            raise HTTPException(404, "No such task")
        row = planned(conn, team_id).get(task)
        title = body.title or (row["title"] if row else None) or next(
            (t["title"] for t in build_board(conn, team_id, name)["tasks"] if t["task"] == task), "") or task
        owner_id, owner = member_named(conn, team_id, body.owner) if body.owner is not None else (None, None)
        state = body.state or (row["state"] if row else "open")
        if body.owner is None and row:  # keep the current owner
            current = conn.execute("select owner_id, owner_name from tasks where team_id = %s and task = %s", (team_id, task)).fetchone()
            owner_id, owner = (str(current["owner_id"]) if current["owner_id"] else None), current["owner_name"]
        due = (body.due or None) if body.due is not None else (row["due"] if row else None)
        conn.execute("insert into tasks (team_id, task, title, owner_id, owner_name, state, created_by, due) values"
                     " (%s, %s, %s, %s, %s, %s, %s, %s) on conflict (team_id, task) do update set title = excluded.title,"
                     " owner_id = excluded.owner_id, owner_name = excluded.owner_name, state = excluded.state,"
                     " due = excluded.due, updated_at = now()",
                     (team_id, task, title[:120], owner_id, owner, state, c.person.id, due))
        return {"task": task, "title": title[:120], "owner": owner, "state": state, "due": due}

    @app.delete("/v1/tasks/{task}")
    def delete_task(task: str, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        """Undo a planned task. Session history is never deleted, only the plan."""
        if c.kind != "session":
            raise HTTPException(401, "Sign in first")
        team_id, _, _ = team_scope(c, team, conn)
        if not conn.execute("delete from tasks where team_id = %s and task = %s", (team_id, task)).rowcount:
            raise HTTPException(404, "No planned task with that id")
        return {"ok": True}

    @app.post("/v1/agent")
    def agent_turn(body: AgentIn, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        """One turn of the Super Agents chat: an answer with citations, a plan (plan mode) and proposed board changes,
        which the app applies by mode. The model picker pins a Nemotron tier; Auto uses Ultra for plans and imports."""
        if c.kind != "session":
            raise HTTPException(401, "Sign in first")
        if not asks.allow(c.person.id, time.time()):
            raise HTTPException(429, "Lots of questions just now; try again in a few minutes")
        team_id, name, _ = team_scope(c, team, conn)
        board = [{k: t.get(k) for k in ("task", "title", "status", "owner")} for t in build_board(conn, team_id, name)["tasks"]]
        members = [r["name"] for r in conn.execute("select name from memberships where team_id = %s and removed_at is null"
                                                   " order by created_at", (team_id,))]
        tier = body.model if body.model != "auto" else ("ultra" if body.mode == "plan" or body.attachments else None)
        try:
            with llm.pinned(tier), llm.meter() as used:
                out = agent.turn(body.message, task_events(conn, team_id), board, members,
                                 [a.model_dump() for a in body.attachments], body.mode, chat=chat)
        except Exception:  # noqa: BLE001
            raise HTTPException(503, "Agent S couldn't answer right now; try again in a minute") from None
        record_usage(conn, team_id, c.person, "agent", used)
        return {**out, "mode": body.mode}

    @app.post("/v1/llm")
    def llm_step(body: LlmIn, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        """One step of an agent's tool loop for the Super Agents app, on the hub's Nemotron key: signed-in people
        only, rate limited, size capped. The loop and the tools run on the person's laptop. With a team, the step's
        tokens count toward that team's usage."""
        if c.kind != "session":
            raise HTTPException(401, "Sign in first")
        team_id = team_scope(c, team, conn)[0] if team else None
        if not llm_steps.allow(c.person.id, time.time()):
            raise HTTPException(429, "Agents are busy; give it a minute")
        if len(json.dumps(body.messages)) + len(json.dumps(body.tools)) > 400_000:
            raise HTTPException(413, "That conversation is too long; start a new chat")
        try:
            with llm.pinned(body.tier), llm.effort(body.effort):
                out = chat_step(body.messages, body.tools, body.max_tokens)
        except urllib.error.HTTPError as e:
            raise HTTPException(502, f"The model refused the request ({e.code})") from None
        except Exception:  # noqa: BLE001
            raise HTTPException(503, "The model didn't answer; try again in a moment") from None
        if team_id and out.get("usage"):
            record_usage(conn, team_id, c.person, "app", {"calls": 1, "model": out.get("model"), **out["usage"]})
        return out

    @app.get("/v1/events")
    def cited_events(ids: str, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        """The events behind an answer's citations (at most 20), oldest first, each with its one-line description."""
        wanted = [i for i in ids.split(",") if ID_RE.match(i)][:20]
        if team == "demo" or (c.kind == "anon" and not team):
            evs = [e for e in demo.events() if e["id"] in wanted]
        else:
            rows = conn.execute("select body from events where team_id = %s and id = any(%s) order by ts",
                                (team_scope(c, team, conn)[0], wanted)).fetchall() if wanted else []
            evs = [r["body"] for r in rows]
        return {"events": [{"id": e["id"], "ts": e.get("ts"), "member": e.get("member"), "tool": e.get("tool"),
                            "task": e.get("task"), "kind": e.get("kind"), "line": progress.describe(e)} for e in evs]}

    @app.get("/v1/team")
    def team_view(team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        if team == "demo" or (c.kind == "anon" and not team):
            return demo.team()
        team_id, name, role = team_scope(c, team, conn)
        now = time.time()
        rows = conn.execute(
            "select m.user_id, m.name, m.email, m.role, m.removed_at, e.task, e.body->>'tool' as tool,"
            " extract(epoch from e.received_at) as at from memberships m left join events e"
            " on e.team_id = m.team_id and e.user_id = m.user_id where m.team_id = %s", (team_id,)).fetchall()
        people: dict[str, dict] = {}
        for r in rows:
            p = people.setdefault(str(r["user_id"]), {"user_id": str(r["user_id"]), "name": r["name"], "member_role": r["role"],
                                                      "email": r["email"] if role == "lead" else None, "tools": set(),
                                                      "tasks": {}, "last_activity": 0.0, "removed": r["removed_at"] is not None})
            if r["at"] is not None:
                at = float(r["at"])
                p["last_activity"] = max(p["last_activity"], at)
                if r["tool"] in ("claude_code", "codex", "cursor"):
                    p["tools"].add(r["tool"])
                if r["task"]:
                    p["tasks"][r["task"]] = max(p["tasks"].get(r["task"], 0), at)
        members = []
        for p in sorted(people.values(), key=lambda p: -p["last_activity"]):
            members.append({**p, "tools": sorted(p["tools"]), "active": now - p["last_activity"] < ACTIVE_SECONDS,
                            "tasks": [{"task": t, "last_activity": a} for t, a in sorted(p["tasks"].items(), key=lambda x: -x[1])]})
        return {"room": name, "demo": False, "role": role, "members": members}

    @app.post("/v1/ask")
    def ask(body: AskIn, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        who = c.person.id if c.person else "anon"
        if not asks.allow(who, time.time()):
            raise HTTPException(429, "Lots of questions just now; try again in a few minutes")
        team_id = None if (team == "demo" or (c.kind == "anon" and not team)) else team_scope(c, team, conn)[0]
        evs = task_events(conn, team_id) if team_id else demo.events()
        try:
            with llm.meter() as used:
                out = qa.answer(body.question, evs, chat=chat)
        except Exception:  # noqa: BLE001
            raise HTTPException(503, "Agent S couldn't answer right now; try again in a minute") from None
        if team_id:
            record_usage(conn, team_id, c.person, "ask", used)
        return out

    @app.get("/v1/digest")
    def get_digest(team: Optional[str] = None, model: str = "auto", c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        is_demo = team == "demo" or (c.kind == "anon" and not team)
        team_key = "demo" if is_demo else team_scope(c, team, conn)[0]
        key = f"{team_key}:{model}"
        hit = digests.get(key)
        if hit and time.time() - hit[0] < 600:
            return hit[1]
        if is_demo:
            evs = demo.events()
        else:
            rows = conn.execute("select body from events where team_id = %s and received_at > now() - interval '1 day'"
                                " order by ts limit 400", (team_key,)).fetchall()
            evs = [r["body"] for r in rows]
        try:
            with llm.pinned(model), llm.meter() as used:
                out = {**agent_digest.digest(evs, chat=chat), "generated_at": time.time()}
        except Exception:  # noqa: BLE001
            raise HTTPException(503, "Agent S couldn't write the digest right now; try again in a minute") from None
        if not is_demo:
            record_usage(conn, team_key, None, "digest", used)
        digests[key] = (time.time(), out)
        return out

    # ---- Super Team: prompts into teammates' coding sessions -------------------------------------------
    # Someone in the team sends a prompt into a teammate's Claude Code or Codex session. The owner's rules decide:
    # off, ask each time, or automatic; read-only or edit; tokens per teammate per day. The owner's Super Agents runs
    # it as a fork of that session (their live session isn't touched) and reports back. Every prompt stays on record:
    # the lead sees all of them, a member the ones they sent or received.
    ACCESS = {"mode": "ask", "access": "read", "daily_tokens": None, "app_seen_at": None}

    def access_of(conn, team_id: str, user_id: str) -> dict:
        row = conn.execute("select mode, access, daily_tokens, app_seen_at from session_access where team_id = %s and user_id = %s",
                           (team_id, user_id)).fetchone()
        return {**ACCESS, **(row or {})}

    def used_today(conn, team_id: str, from_user: str, to_user: str) -> int:
        return int(conn.execute("select coalesce(sum(tokens), 0) as n from session_prompts where team_id = %s and from_user = %s"
                                " and to_user = %s and created_at >= date_trunc('day', now())", (team_id, from_user, to_user)).fetchone()["n"])

    PROMPT_DAYS = 7  # a prompt that hasn't run in a week expires instead of running late

    def prompt_view(r: dict, me: str) -> dict:
        stale = r["status"] in ("pending", "approved") and r["created_at"] < datetime.now(timezone.utc) - timedelta(days=PROMPT_DAYS)
        return {"id": str(r["id"]), "from": {"id": str(r["from_user"]), "name": r["from_name"]},
                "to": {"id": str(r["to_user"]), "name": r["to_name"]}, "session": r["session"], "tool": r["tool"],
                "repo": r["repo"], "task": r["task"], "prompt": r["prompt"], "access": r["access"],
                "status": "expired" if stale else r["status"],
                "decided_by": r["decided_by"], "tokens": int(r["tokens"] or 0), "result": r["result"],
                "run_session": r["run_session"], "created_at": r["created_at"].timestamp(),
                "finished_at": r["finished_at"].timestamp() if r["finished_at"] else None,
                "yours_to_decide": str(r["to_user"]) == me and r["status"] == "pending",
                "yours": str(r["from_user"]) == me}

    def session_scope(c: Caller, team: Optional[str], conn) -> tuple[str, str]:
        if c.kind != "session":
            raise HTTPException(401, "Sign in first")
        team_id, _, role = team_scope(c, team, conn)
        return team_id, role

    def session_card(r: dict, rules: dict, threads: dict, me: str, conn, team_id: str, now: float) -> dict:
        uid = str(r["user_id"])
        a = {**ACCESS, **rules.get(uid, {})}
        seen = a["app_seen_at"].timestamp() if a["app_seen_at"] else 0
        return {"session": r["session"], "tool": r["tool"], "owner": {"id": uid, "name": r["member"]}, "repo": r["repo"],
                "branch": r["branch"], "task": r["task"], "last": float(r["last"]), "turns": int(r["turns"]),
                "ended": bool(r["ended"]), "active": now - float(r["last"]) < ACTIVE_SECONDS, "mine": uid == me,
                "mode": a["mode"], "access": a["access"], "daily_tokens": a["daily_tokens"],
                "app_online": now - seen < 120, "app_seen": seen or None, "thread": threads.get(r["session"], 0),
                "used_today": used_today(conn, team_id, me, uid) if uid != me else 0}

    SESSION_SQL = ("select e.user_id, max(e.member) as member, e.body->>'session' as session, max(e.body->>'tool') as tool,"
                   " max(e.body->>'repo') as repo, max(e.body->>'branch') as branch, max(e.task) as task,"
                   " extract(epoch from max(e.received_at)) as last, count(*) filter (where e.kind = 'turn_end') as turns,"
                   " bool_or(e.kind = 'session_end') as ended from events e join memberships m on m.team_id = e.team_id"
                   " and m.user_id = e.user_id and m.removed_at is null where e.team_id = %s and e.body->>'tool' in"
                   " ('claude_code', 'codex') and {where} group by e.user_id, e.body->>'session' order by last desc limit {limit}")

    def thread_counts(conn, team_id: str, role: str, me: str) -> dict:
        mine = "" if role == "lead" else " and (from_user = %s or to_user = %s)"
        return {r["session"]: int(r["n"]) for r in conn.execute(
            f"select session, count(*) as n from session_prompts where team_id = %s{mine} group by session",
            (team_id,) if role == "lead" else (team_id, me, me))}

    @app.get("/v1/sessions")
    def team_sessions(team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        """Teammates' coding sessions from the last two weeks (a closed laptop doesn't hide them), each with its owner's
        rules for prompts and how many prompts are in its thread."""
        team_id, role = session_scope(c, team, conn)
        rows = conn.execute(SESSION_SQL.format(where="e.received_at > now() - interval '14 days' and e.body->>'session' is not null",
                                               limit=80), (team_id,)).fetchall()
        now = time.time()
        rules = {str(r["user_id"]): r for r in conn.execute(
            "select user_id, mode, access, daily_tokens, app_seen_at from session_access where team_id = %s", (team_id,))}
        threads = thread_counts(conn, team_id, role, c.person.id)
        mine = access_of(conn, team_id, c.person.id)
        return {"sessions": [session_card(r, rules, threads, c.person.id, conn, team_id, now) for r in rows], "role": role,
                "me": {k: mine[k] for k in ("mode", "access", "daily_tokens")}}

    @app.get("/v1/sessions/{session}/thread")
    def session_thread(session: str, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        """One session's Super Team thread: the session, and the prompts into it you may see, oldest first. It's saved,
        so it reads the same while the owner's laptop is closed; prompts sent then wait and run when it's back."""
        team_id, role = session_scope(c, team, conn)
        me = c.person.id
        r = conn.execute(SESSION_SQL.format(where="e.body->>'session' = %s", limit=1), (team_id, session)).fetchone()
        mine = "" if role == "lead" else " and (from_user = %s or to_user = %s)"
        rows = conn.execute(f"select * from session_prompts where team_id = %s and session = %s{mine} order by created_at limit 200",
                            (team_id, session) if role == "lead" else (team_id, session, me, me)).fetchall()
        if not r:
            raise HTTPException(404, "No such session in this team")
        rules = {str(x["user_id"]): x for x in conn.execute(
            "select user_id, mode, access, daily_tokens, app_seen_at from session_access where team_id = %s and user_id = %s",
            (team_id, r["user_id"]))}
        return {"session": session_card(r, rules, {session: len(rows)}, me, conn, team_id, time.time()),
                "prompts": [prompt_view(x, me) for x in rows], "role": role}

    @app.put("/v1/sessions/access")
    def set_access(body: AccessIn, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        """Your rules for teammates' prompts into your sessions."""
        team_id, _ = session_scope(c, team, conn)
        conn.execute("insert into session_access (team_id, user_id, mode, access, daily_tokens) values (%s, %s, %s, %s, %s)"
                     " on conflict (team_id, user_id) do update set mode = excluded.mode, access = excluded.access,"
                     " daily_tokens = excluded.daily_tokens, updated_at = now()",
                     (team_id, c.person.id, body.mode, body.access, body.daily_tokens))
        return body.model_dump()

    @app.post("/v1/prompts")
    def send_prompt(body: PromptIn, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, _ = session_scope(c, team, conn)
        s = conn.execute(
            "select e.user_id, max(e.member) as member, max(e.body->>'tool') as tool, max(e.body->>'repo') as repo,"
            " max(e.task) as task from events e join memberships m on m.team_id = e.team_id and m.user_id = e.user_id"
            " and m.removed_at is null where e.team_id = %s and e.body->>'session' = %s group by e.user_id",
            (team_id, body.session)).fetchone()
        if not s:
            raise HTTPException(404, "No such session in this team")
        owner = str(s["user_id"])
        if owner == c.person.id:
            raise HTTPException(400, "That's your own session")
        if s["tool"] not in ("claude_code", "codex"):
            raise HTTPException(400, "Only Claude Code and Codex sessions take prompts")
        rules = access_of(conn, team_id, owner)
        if rules["mode"] == "off":
            raise HTTPException(403, f"{s['member']} isn't taking prompts into their sessions")
        if rules["daily_tokens"] and used_today(conn, team_id, c.person.id, owner) >= rules["daily_tokens"]:
            raise HTTPException(429, f"You've used today's {rules['daily_tokens']:,} tokens of {s['member']}'s sessions")
        auto = rules["mode"] == "auto"
        row = conn.execute(
            "insert into session_prompts (team_id, from_user, from_name, to_user, to_name, session, tool, repo, task, prompt,"
            " access, status, decided_by, decided_at) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " case when %s then now() end) returning *",
            (team_id, c.person.id, c.person.name, owner, s["member"], body.session, s["tool"], s["repo"], s["task"],
             body.prompt.strip(), rules["access"], "approved" if auto else "pending", "auto" if auto else None, auto)).fetchone()
        return prompt_view(row, c.person.id)

    @app.get("/v1/prompts")
    def list_prompts(team: Optional[str] = None, box: str = "all", limit: int = 50, c: Caller = Depends(caller),
                     conn=Depends(db)) -> dict:
        """The record of prompts into sessions. The lead sees the whole team's; a member, what they sent or received."""
        team_id, role = session_scope(c, team, conn)
        me = c.person.id
        where, params = "team_id = %s", [team_id]
        if box == "in":
            where, params = where + " and to_user = %s", params + [me]
        elif box == "out":
            where, params = where + " and from_user = %s", params + [me]
        elif role != "lead":
            where, params = where + " and (from_user = %s or to_user = %s)", params + [me, me]
        rows = conn.execute(f"select * from session_prompts where {where} order by created_at desc limit %s",
                            (*params, max(1, min(limit, 200)))).fetchall()
        return {"prompts": [prompt_view(r, me) for r in rows], "role": role}

    @app.get("/v1/prompts/runnable")
    def runnable(team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        """The owner's Super Agents asks for approved prompts to run (and so shows as online to the team)."""
        team_id, _ = session_scope(c, team, conn)
        conn.execute("insert into session_access (team_id, user_id, app_seen_at) values (%s, %s, now()) on conflict"
                     " (team_id, user_id) do update set app_seen_at = now()", (team_id, c.person.id))
        rows = conn.execute("select * from session_prompts where team_id = %s and to_user = %s and status = 'approved'"
                            " and created_at > now() - make_interval(days => %s) order by created_at limit 5",
                            (team_id, c.person.id, PROMPT_DAYS)).fetchall()
        return {"prompts": [prompt_view(r, c.person.id) for r in rows]}

    def visible_prompt(conn, team_id: str, role: str, pid: str, me: str) -> dict:
        try:
            row = conn.execute("select * from session_prompts where team_id = %s and id = %s", (team_id, _uuid_or_400(pid))).fetchone()
        except HTTPException:
            raise HTTPException(404, "No such prompt") from None
        if not row or (role != "lead" and me not in (str(row["from_user"]), str(row["to_user"]))):
            raise HTTPException(404, "No such prompt")
        return row

    @app.get("/v1/prompts/{pid}")
    def get_prompt(pid: str, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, role = session_scope(c, team, conn)
        return prompt_view(visible_prompt(conn, team_id, role, pid, c.person.id), c.person.id)

    def change_prompt(conn, team_id: str, pid: str, sql: str, params: tuple, why: str) -> dict:
        row = conn.execute(f"update session_prompts set {sql} returning *", params).fetchone()
        if not row:
            raise HTTPException(409, why)
        return row

    @app.post("/v1/prompts/{pid}/decide")
    def decide_prompt(pid: str, body: DecideIn, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, role = session_scope(c, team, conn)
        visible_prompt(conn, team_id, role, pid, c.person.id)
        row = change_prompt(conn, team_id, pid, "status = %s, decided_by = 'owner', decided_at = now() where team_id = %s"
                            " and id = %s and to_user = %s and status = 'pending' and created_at > now() - make_interval(days => %s)",
                            ("approved" if body.approve else "denied", team_id, pid, c.person.id, PROMPT_DAYS),
                            "Only the session's owner can decide, once, within a week")
        return prompt_view(row, c.person.id)

    @app.post("/v1/prompts/{pid}/cancel")
    def cancel_prompt(pid: str, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, role = session_scope(c, team, conn)
        visible_prompt(conn, team_id, role, pid, c.person.id)
        row = change_prompt(conn, team_id, pid, "status = 'cancelled', finished_at = now() where team_id = %s and id = %s"
                            " and from_user = %s and status in ('pending', 'approved')", (team_id, pid, c.person.id),
                            "Only a prompt you sent that hasn't started can be cancelled")
        return prompt_view(row, c.person.id)

    @app.post("/v1/prompts/{pid}/claim")
    def claim_prompt(pid: str, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        """The owner's Super Agents takes an approved prompt to run, with what's left of the teammate's tokens today."""
        team_id, role = session_scope(c, team, conn)
        row = visible_prompt(conn, team_id, role, pid, c.person.id)
        limit = access_of(conn, team_id, c.person.id)["daily_tokens"]
        budget = None if not limit else max(0, limit - used_today(conn, team_id, str(row["from_user"]), c.person.id))
        if budget == 0:
            change_prompt(conn, team_id, pid, "status = 'stopped', result = %s, finished_at = now() where team_id = %s and id = %s"
                          " and to_user = %s and status = 'approved'", ("Not run: the daily token limit is used up.", team_id, pid,
                                                                         c.person.id), "Not yours to run")
            raise HTTPException(429, "That teammate's tokens for today are used up")
        row = change_prompt(conn, team_id, pid, "status = 'running', budget = %s where team_id = %s and id = %s and to_user = %s"
                            " and status = 'approved'", (budget, team_id, pid, c.person.id), "Not yours to run, or already running")
        earlier = conn.execute("select prompt, result from session_prompts where team_id = %s and session = %s and from_user = %s"
                               " and status = 'done' and id <> %s order by created_at desc limit 3",
                               (team_id, row["session"], row["from_user"], row["id"])).fetchall()
        # the thread so far, so a follow-up is answered as a follow-up even though each run starts from the live session
        return {**prompt_view(row, c.person.id), "budget": budget,
                "thread": [{"prompt": e["prompt"], "result": (e["result"] or "")[:2000]} for e in reversed(earlier)]}

    @app.post("/v1/prompts/{pid}/finish")
    def finish_prompt(pid: str, body: FinishIn, team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        team_id, role = session_scope(c, team, conn)
        visible_prompt(conn, team_id, role, pid, c.person.id)
        row = change_prompt(conn, team_id, pid, "status = %s, result = %s, tokens = %s, run_session = %s, finished_at = now()"
                            " where team_id = %s and id = %s and to_user = %s and status = 'running'",
                            (body.status, body.result, body.tokens, body.run_session, team_id, pid, c.person.id), "Not running")
        return prompt_view(row, c.person.id)

    @app.get("/v1/usage")
    def usage_view(team: Optional[str] = None, days: int = 7, tz: int = 0, c: Caller = Depends(caller),
                   conn=Depends(db)) -> dict:
        """The usage counter: tokens by day, tool, task, model and person (people: the lead sees everyone, a member
        sees themself). tz is the viewer's offset from UTC in minutes, so "today" is their today."""
        team_id, name, role = team_scope(c, team, conn)
        days, tz = max(1, min(days, RETENTION_DAYS)), max(-720, min(tz, 840))
        rows = conn.execute(
            "select user_id, member, task, body->>'tool' as tool, body->>'session' as session, body->>'ts' as ts,"
            " body->'facts'->'usage' as usage, extract(epoch from received_at) as received from events where team_id = %s"
            " and kind = 'turn_end' and received_at > now() - make_interval(days => %s)"
            " and body->'facts'->'usage' is not null", (team_id, days + 1)).fetchall()
        turns = [{**r, "user_id": str(r["user_id"]) if r["user_id"] else None, "at": _epoch(r["ts"]) or float(r["received"])}
                 for r in rows]
        spent = conn.execute(
            "select user_id, member, source, model, calls, tokens_in, tokens_out, extract(epoch from at) as at from agent_usage"
            " where team_id = %s and at > now() - make_interval(days => %s)", (team_id, days + 1)).fetchall()
        spent = [{**a, "user_id": str(a["user_id"]) if a["user_id"] else None, "at": float(a["at"])} for a in spent]
        prompted = conn.execute(
            "select from_name, to_name, count(*) as prompts, coalesce(sum(tokens), 0) as tokens from session_prompts where"
            " team_id = %s and created_at > now() - make_interval(days => %s) and status in ('running', 'done', 'failed', 'stopped')"
            + ("" if role == "lead" else " and (from_user = %s or to_user = %s)") + " group by from_name, to_name order by tokens desc",
            (team_id, days) if role == "lead" else (team_id, days, c.person.id, c.person.id)).fetchall()
        return {**usage_sum.summarize(turns, spent, me=c.person.id, lead=role == "lead", days=days, tz_minutes=tz,
                                      now=time.time()), "room": name, "role": role,
                "prompted": [{"from": r["from_name"], "to": r["to_name"], "prompts": int(r["prompts"]), "tokens": int(r["tokens"])}
                             for r in prompted]}

    return app


def _epoch(ts: Optional[str]) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class _Demo:
    """The public sample team, served from hub/hub/demo/demo.json without a database."""

    def __init__(self) -> None:
        data = json.loads(DEMO_FILE.read_text(encoding="utf-8"))
        now = time.time()
        self._events, self._snaps = [], data["snapshots"]
        for e in data["events"]:
            e = dict(e)
            at = now - e.pop("offset_min") * 60
            e["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(at)) + ".000Z"
            e["_at"] = at
            self._events.append(e)
        self._events.sort(key=lambda e: e["ts"])

    def events(self) -> list[dict]:
        return [{k: v for k, v in e.items() if k != "_at"} for e in self._events]

    def _by_task(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for e in self._events:
            if e.get("task"):
                out.setdefault(e["task"], []).append(e)
        return out

    def board(self) -> dict:
        now = time.time()
        tasks = sorted(self._by_task().items(), key=lambda kv: -max(e["_at"] for e in kv[1]))
        people: dict[str, float] = {}
        for e in self._events:
            if e["member"] != "github":
                people[e["member"]] = max(people.get(e["member"], 0), e["_at"])
        return {"room": "demo", "generated_at": now, "demo": True, "role": "viewer",
                "tasks": [cards.card(t, evs, self._snaps.get(t), max(e["_at"] for e in evs), len(evs)) for t, evs in tasks],
                "members": [{"name": n, "last_activity": a, "active": now - a < ACTIVE_SECONDS} for n, a in people.items()]}

    def task(self, task: str) -> dict:
        evs = self._by_task().get(task)
        if not evs:
            raise HTTPException(404, "No activity for this task")
        card = cards.card(task, evs, self._snaps.get(task), max(e["_at"] for e in evs), len(evs))
        snap = self._snaps.get(task) or {}
        return {**{k: card.get(k) for k in ("task", "title", "status", "pr", "members", "tools", "progress")},
                "history": [{"at": time.time(), "percent": snap.get("percent"), "agent_says": snap.get("agent_says_percent")}] if snap else [],
                "timeline": cards.timeline(evs)}

    def team(self) -> dict:
        now, people = time.time(), {}
        for e in self._events:
            if e["member"] == "github":
                continue
            p = people.setdefault(e["member"], {"name": e["member"], "tools": set(), "tasks": {}, "last_activity": 0.0})
            p["last_activity"] = max(p["last_activity"], e["_at"])
            if e.get("tool") in ("claude_code", "codex", "cursor"):
                p["tools"].add(e["tool"])
            if e.get("task"):
                p["tasks"][e["task"]] = max(p["tasks"].get(e["task"], 0), e["_at"])
        return {"room": "demo", "demo": True, "role": "viewer",
                "members": [{**p, "tools": sorted(p["tools"]), "active": now - p["last_activity"] < ACTIVE_SECONDS, "removed": False,
                             "tasks": [{"task": t, "last_activity": a} for t, a in sorted(p["tasks"].items(), key=lambda x: -x[1])]}
                            for p in sorted(people.values(), key=lambda p: -p["last_activity"])]}
