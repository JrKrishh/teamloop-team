"""TeamLoop cloud hub: Vercel + Supabase. The API shapes match the self-hosted hub (hub/), so the same board page
and the same connector work against both; the differences are who you are (a Supabase sign-in, not a room token)
and where data lives (Postgres, per team). docs/cloud.md.

Env: DATABASE_URL (Supabase transaction pooler), SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, NEBIUS_API_KEY,
PUBLIC_URL (optional; used in invite and sign-in links), HUB_SECURE_COOKIE (default on).
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import hub
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from agent_s import digest as agent_digest
from agent_s import llm, progress, qa
from hub import cards
from hub.relay import _Window
from hub.team import ID_RE, KIND_RE, MAX_EVENT_BYTES, TASK_RE, clean

from . import __version__, auth

STATIC = Path(hub.__file__).parent / "static"
DEMO_FILE = Path(hub.__file__).parent / "demo" / "demo.json"
ACTIVE_SECONDS = 300
DEBOUNCE_SECONDS = 30
RETENTION_DAYS = 30
CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ23456789"  # no vowels: device codes never spell words


# ---- request plumbing -----------------------------------------------------------------------------
def db():
    """One short-lived connection per request: on Vercel any request may land on a fresh instance. Supabase's
    transaction pooler doesn't support prepared statements, hence prepare_threshold=None."""
    conn = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, prepare_threshold=None, connect_timeout=10)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
    tok = request.cookies.get(auth.SESSION_COOKIE)
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


class EventsIn(BaseModel):
    events: list[dict] = Field(max_length=50)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class DeviceStartIn(BaseModel):
    label: str = Field(default="", max_length=60)


class DeviceApproveIn(BaseModel):
    user_code: str = Field(min_length=9, max_length=9)
    team: str


# ---- the app --------------------------------------------------------------------------------------
def create(chat: Optional[Callable] = None) -> FastAPI:
    chat = chat or llm.chat_json
    app = FastAPI(title="TeamLoop cloud", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    posts = _Window(60, 60.0)
    asks = _Window(30, 600.0)
    digests: dict[str, tuple[float, dict]] = {}
    failed: dict[tuple[str, str], float] = {}
    demo = _Demo()

    import mimetypes

    mimetypes.add_type("image/webp", ".webp")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def page() -> FileResponse:
        return FileResponse(STATIC / "board.html")

    for path in ("/", "/auth", "/device", "/join/{token}"):
        app.add_api_route(path, page, include_in_schema=False)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "version": __version__, "mode": "cloud"}

    @app.get("/v1/config")
    def config() -> dict:
        return {"mode": "cloud", "supabase_url": os.environ.get("SUPABASE_URL"),
                "supabase_key": os.environ.get("SUPABASE_PUBLISHABLE_KEY")}

    # ---- sign-in -----------------------------------------------------------------------------------
    @app.post("/v1/session")
    def session(body: SessionIn, response: Response, conn=Depends(db)) -> dict:
        """Trade a Supabase access token (from GitHub or email/password sign-in) for a hub session cookie."""
        try:
            person = auth.supabase_user(body.access_token)
        except PermissionError as e:
            raise HTTPException(401, str(e)) from None
        tok = auth.new_token("s_")
        conn.execute("insert into hub_sessions (token_hash, user_id, email, name, expires_at) values (%s, %s, %s, %s, %s)",
                     (auth.digest(tok), person.id, person.email, person.name,
                      datetime.now(timezone.utc) + timedelta(days=auth.SESSION_DAYS)))
        response.set_cookie(auth.SESSION_COOKIE, tok, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                            secure=os.getenv("HUB_SECURE_COOKIE", "1") != "0")
        return {"user": {"id": person.id, "email": person.email, "name": person.name}}

    @app.post("/v1/logout")
    def logout(request: Request, response: Response, conn=Depends(db)) -> dict:
        tok = request.cookies.get(auth.SESSION_COOKIE)
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
            conn.execute("delete from hub_sessions where expires_at < now()")
            conn.execute("delete from devices where expires_at < now() - interval '1 day'")
        return {"accepted": new, "duplicates": len(rows) - new}

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
        conn.commit()
        return made

    def build_board(conn, team_id: str, team_name: str) -> dict:
        now = time.time()
        tasks = conn.execute("select task, extract(epoch from max(received_at)) as last, count(*) as n from events"
                             " where team_id = %s and task is not null group by task order by last desc limit 60",
                             (team_id,)).fetchall()
        snaps = {r["task"]: r["body"] for r in conn.execute(
            "select distinct on (task) task, body from snapshots where team_id = %s order by task, created_at desc", (team_id,))}
        out = [cards.card(t["task"], task_events(conn, team_id, t["task"], 200), snaps.get(t["task"]), float(t["last"]), t["n"])
               for t in tasks]
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
            raise HTTPException(404, "No activity for this task")
        history = conn.execute("select extract(epoch from created_at) as at, body from snapshots where team_id = %s and task = %s"
                               " order by created_at desc limit 20", (team_id, task)).fetchall()
        card = next((t for t in build_board(conn, team_id, name)["tasks"] if t["task"] == task), {})
        return {**{k: card.get(k) for k in ("task", "title", "status", "pr", "members", "tools", "progress")},
                "history": [{"at": float(h["at"]), "percent": h["body"].get("percent"), "agent_says": h["body"].get("agent_says_percent")}
                            for h in reversed(history)],
                "timeline": cards.timeline(evs)}

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
        evs = demo.events() if (team == "demo" or (c.kind == "anon" and not team)) else task_events(conn, team_scope(c, team, conn)[0])
        try:
            return qa.answer(body.question, evs, chat=chat)
        except Exception:  # noqa: BLE001
            raise HTTPException(503, "Agent S couldn't answer right now; try again in a minute") from None

    @app.get("/v1/digest")
    def get_digest(team: Optional[str] = None, c: Caller = Depends(caller), conn=Depends(db)) -> dict:
        is_demo = team == "demo" or (c.kind == "anon" and not team)
        key = "demo" if is_demo else team_scope(c, team, conn)[0]
        hit = digests.get(key)
        if hit and time.time() - hit[0] < 600:
            return hit[1]
        if is_demo:
            evs = demo.events()
        else:
            rows = conn.execute("select body from events where team_id = %s and received_at > now() - interval '1 day'"
                                " order by ts limit 400", (key,)).fetchall()
            evs = [r["body"] for r in rows]
        try:
            out = {**agent_digest.digest(evs, chat=chat), "generated_at": time.time()}
        except Exception:  # noqa: BLE001
            raise HTTPException(503, "Agent S couldn't write the digest right now; try again in a minute") from None
        digests[key] = (time.time(), out)
        return out

    return app


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
