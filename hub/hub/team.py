"""TeamLoop on top of the ccbridge relay: events in, Agent S progress and answers out (docs/hub-api.md).

Auth is ccbridge's: a member joins the room (room token + identity key) and sends with its session.
The lead's browser signs in with the room token once and gets a cookie (EventSource can't send headers).
Peer text that agents or the board will read (summaries, self-reports) goes through ccbridge's sanitize()
first, so one teammate's agent output can't steer Agent S or another agent.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent_s import digest, llm, progress, qa

from . import cards, notify
from .safety import NAME_RE, ROOM_RE, sanitize

log = logging.getLogger("teamloop.hub")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    room        TEXT NOT NULL,
    member      TEXT NOT NULL,
    task        TEXT,
    kind        TEXT NOT NULL,
    ts          TEXT NOT NULL,
    body        TEXT NOT NULL,
    received_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_room_task ON events (room, task, ts);
CREATE TABLE IF NOT EXISTS snapshots (
    room       TEXT NOT NULL,
    task       TEXT NOT NULL,
    created_at REAL NOT NULL,
    body       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots ON snapshots (room, task, created_at);
CREATE TABLE IF NOT EXISTS removed (
    room TEXT NOT NULL,
    name TEXT NOT NULL,
    at   REAL NOT NULL,
    PRIMARY KEY (room, name)
);
"""
ID_RE = re.compile(r"^[0-9a-f]{32}$")
KIND_RE = re.compile(r"^[a-z_]{1,32}$")
TASK_RE = re.compile(r"^[A-Z][A-Z0-9]{0,15}-\d{1,8}$")
ACTIVE_SECONDS = 300
COOKIE = "teamloop_board"
MAX_STREAMS_PER_ROOM = 25
MAX_EVENT_BYTES = 8192  # ccbridge's message cap
POSTS_PER_MINUTE = int(os.getenv("HUB_POSTS_PER_MINUTE", "60"))
RETENTION_DAYS = float(os.getenv("HUB_RETENTION_DAYS", "30"))
KEEP_SNAPSHOTS = 20
DIGEST_CACHE_SECONDS = 600
STREAM_POLL_SECONDS = float(os.getenv("HUB_STREAM_POLL", "1"))
STATIC = Path(__file__).parent / "static"
COOKIE_DAYS = 7


class EventsIn(BaseModel):
    events: list[dict] = Field(max_length=50)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True)
class Access:
    room: str
    role: str                   # "lead", "member" or "viewer"
    name: Optional[str] = None  # set for connector sessions


class BoardLogin(BaseModel):
    room: str = Field(max_length=64)
    token: str = Field(min_length=1, max_length=256)


def _clean_text(value):
    if isinstance(value, str):
        return sanitize(value)[0]
    if isinstance(value, list):
        return [_clean_text(v) for v in value]
    return value


def clean(event: dict) -> dict:
    out = dict(event)
    if isinstance(out.get("summary"), str):
        out["summary"] = _clean_text(out["summary"])
    if isinstance(out.get("report"), dict):
        out["report"] = {k: _clean_text(v) for k, v in out["report"].items()}
    if isinstance(out.get("push"), dict):  # teammates' agents read these subjects too
        out["push"] = {**out["push"], "commits": [{**c, "subject": _clean_text(c.get("subject"))} for c in out["push"].get("commits", [])]}
    return out


def bad_shape(e: dict) -> Optional[str]:
    """Why an incoming event can't be stored, or None. The board, Agent S and the usage counter read these fields
    without checks, so one malformed event would break its team's board until it aged out. Both hubs use this."""
    if not ID_RE.match(str(e.get("id", ""))) or not KIND_RE.match(str(e.get("kind", ""))):
        return "Each event needs a 32-hex id and a lowercase kind"
    facts, report = e.get("facts", {}), e.get("report", {})
    if not isinstance(e.get("ts"), str) or not isinstance(facts, dict) or not isinstance(report, dict):
        return "An event's ts is text, and its facts and report are objects"
    needs = {"pr": "facts", "review": "facts", "check": "facts", "self_report": "report"}.get(e["kind"])
    if needs and needs not in e:
        return f"A {e['kind']} event needs its {needs}"
    if "cmd" in facts and not (isinstance(facts["cmd"], dict) and isinstance(facts["cmd"].get("kind"), str)):
        return "facts.cmd needs a kind"
    usage = facts.get("usage", {})
    if not isinstance(usage, dict) or any(type(usage.get(k, 0)) is not int or usage.get(k, 0) < 0
                                          for k in ("in", "cw", "cr", "out", "calls")):
        return "facts.usage counts are whole numbers"
    if any(not isinstance(report.get(k, []), list) or not all(isinstance(x, str) for x in report.get(k, []))
           for k in ("done", "next")):
        return "report.done and report.next are lists of text"
    if e["kind"] == "push" and push_shape(e.get("push")):
        return push_shape(e.get("push"))
    return None


def push_shape(p) -> Optional[str]:
    """What's wrong with a push event's commits (connector/teamloop/pushed.py), or None."""
    if not isinstance(p, dict) or not isinstance(p.get("branch"), str) or not isinstance(p.get("commits"), list) or not 0 < len(p["commits"]) <= 50:
        return "A push names its branch and 1 to 50 commits"
    for c in p["commits"]:
        if (not isinstance(c, dict) or not re.fullmatch(r"[0-9a-f]{7,40}", str(c.get("sha", ""))) or not isinstance(c.get("subject"), str)
                or len(c["subject"]) > 200 or not isinstance(c.get("files"), list) or len(c["files"]) > 40
                or not all(isinstance(f, dict) and isinstance(f.get("path"), str) and type(f.get("add")) is int and type(f.get("del")) is int
                           for f in c["files"])):
            return "Each pushed commit has a sha, a subject (200 characters at most) and up to 40 files with line counts"
    return None


def install(app: FastAPI, chat: Optional[Callable] = None, debounce: float = 30.0, every: float = 5.0,
            start_worker: bool = True) -> None:
    conn, lock, caller = app.state.conn, app.state.lock, app.state.caller
    with lock:
        conn.executescript(SCHEMA)
        conn.commit()
    secret = (os.getenv("HUB_SECRET") or secrets.token_hex(32)).encode()
    chat = chat or llm.chat_json
    failed_at: dict[tuple[str, str], float] = {}
    demo_room = os.getenv("HUB_DEMO_ROOM") or None
    from .relay import _Window  # ccbridge's sliding-window limiter

    demo_asks = _Window(int(os.getenv("HUB_DEMO_ASKS_PER_10MIN", "20")), 600.0)
    posts = _Window(POSTS_PER_MINUTE, 60.0)  # per member; the connector sends a batch at most every few seconds

    # ---- the board page ----------------------------------------------------------------------
    mimetypes.add_type("image/webp", ".webp")  # slim Linux images (Vercel) don't know it, and serve octet-stream
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "board.html")

    # ---- who is asking: lead, member or viewer ------------------------------------------------
    # lead:   signed in with the room's lead key (HUB_LEAD_KEYS="room:key,..."), or with the room token when the
    #         room has no lead key. Can invite, remove members, and see settings.
    # member: signed in with the room token, or a connector session. Sees the whole board, like the lead.
    # viewer: the public demo room, read-only.
    from .relay import _hash_token  # the relay's own token hashing

    lead_keys = {room.strip(): _hash_token(key.strip()) for room, _, key in
                 (e.partition(":") for e in os.getenv("HUB_LEAD_KEYS", "").split(",") if ":" in e)}

    def _sign(room: str, role: str, expires: int) -> str:
        mac = hmac.new(secret, f"{room}|{role}|{expires}".encode(), hashlib.sha256).hexdigest()
        return f"{room}|{role}|{expires}|{mac}"

    def access(teamloop_board: Optional[str] = Cookie(default=None),
               authorization: Optional[str] = Header(default=None),
               x_ccbridge_room: Optional[str] = Header(default=None),
               x_ccbridge_session: Optional[str] = Header(default=None)) -> Access:
        if teamloop_board:
            parts = teamloop_board.split("|")
            if len(parts) == 4:
                room, role, expires, _ = parts
                if role in ("lead", "member") and expires.isdigit() and int(expires) > time.time() and \
                        hmac.compare_digest(teamloop_board, _sign(room, role, int(expires))):
                    return Access(room, role, None)
        if demo_room and not authorization:  # public demo: read the demo room's board, never write
            return Access(demo_room, "viewer", None)
        who = caller(authorization, x_ccbridge_room, x_ccbridge_session)
        return Access(who.room, "member", who.display_name)

    def board_room(a: Access = Depends(access)) -> str:
        return a.room

    def lead_only(a: Access = Depends(access)) -> Access:
        if a.role != "lead":
            raise HTTPException(403, "Only the team lead can do that")
        return a

    @app.post("/v1/board/login")
    def board_login(req: BoardLogin, response: Response) -> dict:
        if not ROOM_RE.match(req.room):
            raise HTTPException(400, "Invalid room name")
        given, lead_hash = _hash_token(req.token), lead_keys.get(req.room)
        if lead_hash and hmac.compare_digest(lead_hash, given):
            role = "lead"
        else:
            with lock:
                row = conn.execute("SELECT token_hash FROM rooms WHERE room = ?", (req.room,)).fetchone()
            if row is None or not hmac.compare_digest(row["token_hash"], given):
                raise HTTPException(403, "Unknown room or wrong token")
            role = "member" if lead_hash else "lead"  # no lead key set: whoever holds the room token leads
        expires = int(time.time()) + COOKIE_DAYS * 86400
        response.set_cookie(COOKIE, _sign(req.room, role, expires), max_age=COOKIE_DAYS * 86400, httponly=True,
                            samesite="strict", secure=os.getenv("HUB_SECURE_COOKIE", "1") != "0")
        return {"ok": True, "room": req.room, "role": role}

    @app.get("/v1/me")
    def me(a: Access = Depends(access)) -> dict:
        return {"room": a.room, "role": a.role, "name": a.name, "demo": a.room == demo_room}

    # ---- lead-only: remove a member, see settings -----------------------------------------------
    @app.delete("/v1/members/{name}")
    def remove_member(name: str, a: Access = Depends(lead_only)) -> dict:
        """Revoke a member: their identity key stops working (so the name can't be rejoined with it), their
        sessions end, and any event they still send is refused. Their history stays on the board."""
        if not NAME_RE.match(name):
            raise HTTPException(400, "Invalid name")
        with lock:
            if not conn.execute("SELECT 1 FROM identities WHERE room = ? AND display_name = ?", (a.room, name)).fetchone():
                raise HTTPException(404, "No one by that name has joined this room")
            conn.execute("UPDATE identities SET key_hash = ? WHERE room = ? AND display_name = ?",
                         (_hash_token(secrets.token_urlsafe(32)), a.room, name))
            conn.execute("DELETE FROM sessions WHERE room = ? AND display_name = ?", (a.room, name))
            conn.execute("INSERT OR REPLACE INTO removed VALUES (?, ?, ?)", (a.room, name, time.time()))
            conn.commit()
        return {"ok": True, "removed": name}

    @app.post("/v1/members/{name}/restore")
    def restore_member(name: str, a: Access = Depends(lead_only)) -> dict:
        """Let a removed member back in: the name is freed, and they rejoin with `teamloop login`."""
        with lock:
            gone = conn.execute("DELETE FROM removed WHERE room = ? AND name = ?", (a.room, name)).rowcount
            conn.execute("DELETE FROM identities WHERE room = ? AND display_name = ?", (a.room, name))
            conn.commit()
        if not gone:
            raise HTTPException(404, "That member isn't removed")
        return {"ok": True, "restored": name}

    @app.get("/v1/settings")
    def settings(a: Access = Depends(lead_only)) -> dict:
        repos = [repo.strip() for repo, _, room in (e.partition("=") for e in os.getenv("HUB_GITHUB_REPOS", "").split(","))
                 if room.strip() == a.room and repo.strip()]
        return {"room": a.room, "lead_key_set": a.room in lead_keys, "github_repos": repos,
                "github_secret_set": bool(os.getenv("GITHUB_WEBHOOK_SECRET")),
                "notify_webhook_set": bool(os.getenv("HUB_NOTIFY_WEBHOOK")),
                "agent_s_model": llm.model_for("progress"), "retention_days": RETENTION_DAYS,
                "posts_per_minute": POSTS_PER_MINUTE}

    # ---- events in ----------------------------------------------------------------------------
    @app.post("/v1/events")
    def post_events(body: EventsIn, who=Depends(caller)) -> dict:
        now, rows = time.time(), []
        with lock:
            allowed = posts.allow(f"{who.room}\0{who.display_name}", now)
            banned = conn.execute("SELECT 1 FROM removed WHERE room = ? AND name = ?", (who.room, who.display_name)).fetchone()
        if banned:
            raise HTTPException(403, "This member was removed by the team lead")
        if not allowed:
            raise HTTPException(429, "Too many event batches; the connector will retry")
        for e in body.events:
            if "local" in e:
                raise HTTPException(400, "Events must not carry 'local': that text never leaves the laptop")
            if bad_shape(e):
                raise HTTPException(422, bad_shape(e))
            task = e.get("task") if TASK_RE.match(str(e.get("task") or "")) else None
            e = {**clean(e), "member": who.display_name, "task": task}  # the session says who, not the body
            stored = json.dumps(e, ensure_ascii=False)
            if len(stored.encode()) > MAX_EVENT_BYTES:
                raise HTTPException(413, f"An event is over {MAX_EVENT_BYTES} bytes")
            rows.append((e["id"], who.room, who.display_name, task, e["kind"], str(e.get("ts", ""))[:32], stored, now))
        with lock:
            new = [r for r in rows if conn.execute("INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)", r).rowcount]
            conn.commit()
        for r in new:  # only new events, so a redelivered batch never pings twice
            if r[4] == "blocked":
                notify.blocked(r[1], json.loads(r[6]))
        return {"accepted": len(new), "duplicates": len(rows) - len(new)}

    # ---- reads --------------------------------------------------------------------------------
    def events_for(room: str, task: Optional[str] = None, limit: int = 400) -> list[dict]:
        sql = "SELECT body FROM events WHERE room = ?" + (" AND task = ?" if task else "") + " ORDER BY ts DESC LIMIT ?"
        args = (room, task, limit) if task else (room, limit)
        with lock:
            rows = conn.execute(sql, args).fetchall()
        return [json.loads(r["body"]) for r in reversed(rows)]

    def latest_snapshot(room: str, task: str) -> Optional[dict]:
        with lock:
            row = conn.execute("SELECT body FROM snapshots WHERE room = ? AND task = ? ORDER BY created_at DESC LIMIT 1",
                               (room, task)).fetchone()
        return json.loads(row["body"]) if row else None

    def build_board(room: str) -> dict:
        now = time.time()
        with lock:
            tasks = conn.execute(
                "SELECT task, MAX(received_at) AS last, COUNT(*) AS n FROM events WHERE room = ? AND task IS NOT NULL"
                " GROUP BY task ORDER BY last DESC", (room,)).fetchall()
            members = conn.execute("SELECT member, MAX(received_at) AS last FROM events WHERE room = ? AND member != 'github'"
                                   " GROUP BY member",
                                   (room,)).fetchall()
            recent = conn.execute("SELECT body, received_at FROM events WHERE room = ? AND kind = 'tool' AND received_at > ?",
                                  (room, now - cards.EDITING_SECONDS)).fetchall()
        touch = cards.touching([{**json.loads(r["body"]), "_at": r["received_at"]} for r in recent], now)
        out = [{**cards.card(t["task"], events_for(room, t["task"], 200), latest_snapshot(room, t["task"]), t["last"], t["n"]),
                "editing": cards.editing(touch, t["task"])} for t in tasks]
        return {"room": room, "generated_at": now, "tasks": out, "demo": room == demo_room,
                "members": [{"name": m["member"], "last_activity": m["last"], "active": now - m["last"] < ACTIVE_SECONDS}
                            for m in members],
                "touching": touch[:40], "overlaps": cards.overlaps(touch)}

    @app.get("/v1/board")
    def board(room: str = Depends(board_room)) -> dict:
        return build_board(room)

    @app.get("/v1/tasks/{task}")
    def task_detail(task: str, room: str = Depends(board_room)) -> dict:
        """One task's full timeline and Agent S's estimates over time, for the board's detail panel."""
        if not TASK_RE.match(task):
            raise HTTPException(400, "Not a task id")
        evs = events_for(room, task, 400)
        if not evs:
            raise HTTPException(404, "No activity for this task")
        with lock:
            snaps = [json.loads(r["body"]) | {"at": r["created_at"]} for r in conn.execute(
                "SELECT body, created_at FROM snapshots WHERE room = ? AND task = ? ORDER BY created_at", (room, task))]
        card = next((t for t in build_board(room)["tasks"] if t["task"] == task), {})
        return {**{k: card.get(k) for k in ("task", "title", "status", "pr", "members", "tools", "progress")},
                "history": [{"at": s["at"], "percent": s.get("percent"), "agent_says": s.get("agent_says_percent")}
                            for s in snaps][-20:],
                "timeline": cards.timeline(evs)}

    @app.get("/v1/team")
    def team_view(a: Access = Depends(access)) -> dict:
        """Members with their tools and tasks, for the board's Team view."""
        now = time.time()
        with lock:
            rows = conn.execute(
                "SELECT member, task, MAX(received_at) AS last, GROUP_CONCAT(DISTINCT json_extract(body, '$.tool')) AS tools"
                " FROM events WHERE room = ? AND member != 'github' GROUP BY member, task", (a.room,)).fetchall()
            removed = {r["name"] for r in conn.execute("SELECT name FROM removed WHERE room = ?", (a.room,))}
        people: dict[str, dict] = {}
        for r in rows:
            p = people.setdefault(r["member"], {"name": r["member"], "last_activity": 0.0, "tools": set(), "tasks": []})
            p["last_activity"] = max(p["last_activity"], r["last"])
            p["tools"] |= {t for t in (r["tools"] or "").split(",") if t in ("claude_code", "codex", "cursor")}
            if r["task"]:
                p["tasks"].append({"task": r["task"], "last_activity": r["last"]})
        out = []
        for p in sorted(people.values(), key=lambda p: -p["last_activity"]):
            p["tasks"].sort(key=lambda t: -t["last_activity"])
            out.append({**p, "tools": sorted(p["tools"]), "active": now - p["last_activity"] < ACTIVE_SECONDS,
                        "removed": p["name"] in removed})
        return {"room": a.room, "demo": a.room == demo_room, "role": a.role, "members": out}

    # ---- live board (SSE) -----------------------------------------------------------------------
    streams: dict[str, int] = {}

    def room_version(room: str) -> tuple:
        """Changes when the room gets an event or a snapshot, and once a minute (so 'active' dots age out)."""
        with lock:
            ev = conn.execute("SELECT MAX(rowid) FROM events WHERE room = ?", (room,)).fetchone()[0]
            sn = conn.execute("SELECT MAX(rowid) FROM snapshots WHERE room = ?", (room,)).fetchone()[0]
        return ev, sn, int(time.time() // 60)

    @app.get("/v1/stream")
    async def stream(request: Request, room: str = Depends(board_room)) -> StreamingResponse:
        if streams.get(room, 0) >= MAX_STREAMS_PER_ROOM:
            raise HTTPException(429, "Too many open boards for this room")

        async def events():
            streams[room] = streams.get(room, 0) + 1
            last, quiet = None, 0.0
            try:
                while not await request.is_disconnected():
                    version = await run_in_threadpool(room_version, room)
                    if version != last:
                        last = version
                        board = await run_in_threadpool(build_board, room)
                        yield f"event: board\ndata: {json.dumps(board, ensure_ascii=False)}\n\n"
                        quiet = 0.0
                    elif quiet >= 15:
                        yield ": keep-alive\n\n"  # proxies (HF Spaces) drop silent connections
                        quiet = 0.0
                    await asyncio.sleep(STREAM_POLL_SECONDS)
                    quiet += STREAM_POLL_SECONDS
            finally:
                streams[room] -= 1

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    digests: dict[str, tuple[float, dict]] = {}

    @app.get("/v1/digest")
    def get_digest(room: str = Depends(board_room)) -> dict:
        """Last 24 hours, written by the big model; cached per room for 10 minutes to protect the credits."""
        now = time.time()
        hit = digests.get(room)
        if hit and now - hit[0] < DIGEST_CACHE_SECONDS:
            return hit[1]
        with lock:
            rows = conn.execute("SELECT body FROM events WHERE room = ? AND received_at > ? ORDER BY ts",
                                (room, now - 86400)).fetchall()
        try:
            out = {**digest.digest([json.loads(r["body"]) for r in rows], chat=chat), "generated_at": now}
        except Exception as e:  # noqa: BLE001
            log.warning("digest failed: %s", e)
            raise HTTPException(503, "Agent S couldn't write the digest right now; try again in a minute")
        digests[room] = (now, out)
        return out

    @app.post("/v1/ask")
    def ask(req: AskIn, room: str = Depends(board_room)) -> dict:
        if room == demo_room:
            with lock:
                allowed = demo_asks.allow(room, time.time())
            if not allowed:
                raise HTTPException(429, "The public demo is busy; try again in a few minutes")
        try:
            return qa.answer(req.question, events_for(room), chat=chat)
        except Exception as e:  # noqa: BLE001 - the model being down is not the lead's fault
            log.warning("ask failed: %s", e)
            raise HTTPException(503, "Agent S couldn't answer right now; try again in a minute")

    # ---- Agent S progress worker ---------------------------------------------------------------
    def refresh(now: Optional[float] = None) -> list[str]:
        """Re-estimate every task whose events changed and then went quiet for `debounce` seconds."""
        now = time.time() if now is None else now
        with lock:
            due = conn.execute(
                "SELECT e.room, e.task, MAX(e.received_at) AS last FROM events e WHERE e.task IS NOT NULL"
                " GROUP BY e.room, e.task HAVING last <= ? AND last > COALESCE("
                "(SELECT MAX(s.created_at) FROM snapshots s WHERE s.room = e.room AND s.task = e.task), 0)",
                (now - debounce,)).fetchall()
        done = []
        for row in due:
            key = (row["room"], row["task"])
            if now - failed_at.get(key, 0) < 60:
                continue
            evs = events_for(row["room"], row["task"])
            try:
                snap = progress.estimate(row["task"], evs, cards.title_for(row["task"], evs), chat=chat)
            except Exception as e:  # noqa: BLE001 - retry in a minute
                failed_at[key] = now
                log.warning("progress for %s failed: %s", key, e)
                continue
            with lock:
                conn.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?)",
                             (row["room"], row["task"], max(now, row["last"]), json.dumps(snap, ensure_ascii=False)))
                conn.commit()
            done.append(f"{row['room']}/{row['task']}")
        return done

    def prune(now: Optional[float] = None) -> int:
        """The hub faces the internet, so nothing grows forever: events and snapshots older than the retention
        window go, and each task keeps only its latest snapshots."""
        now = time.time() if now is None else now
        cutoff = now - RETENTION_DAYS * 86400
        with lock:
            gone = conn.execute("DELETE FROM events WHERE received_at < ?", (cutoff,)).rowcount
            conn.execute("DELETE FROM snapshots WHERE created_at < ?", (cutoff,))
            conn.execute("DELETE FROM snapshots WHERE rowid NOT IN (SELECT rowid FROM (SELECT rowid, ROW_NUMBER() OVER"
                         " (PARTITION BY room, task ORDER BY created_at DESC) AS n FROM snapshots) WHERE n <= ?)",
                         (KEEP_SNAPSHOTS,))
            conn.commit()
        return gone

    app.state.refresh_progress = refresh
    app.state.build_board = build_board
    app.state.prune_events = prune

    if start_worker:
        def loop() -> None:
            last_prune = 0.0
            while True:
                try:
                    refresh()
                    if time.time() - last_prune > 3600:
                        prune()
                        last_prune = time.time()
                except Exception:  # noqa: BLE001
                    log.exception("progress worker")
                time.sleep(every)

        threading.Thread(target=loop, daemon=True, name="agent-s-progress").start()
