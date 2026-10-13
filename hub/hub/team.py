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
import os
import re
import secrets
import threading
import time
from typing import Callable, Optional

from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent_s import digest, llm, progress, qa

from .safety import ROOM_RE, sanitize

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
    return out


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
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "board.html")

    # ---- board sign-in (cookie) -------------------------------------------------------------
    def _sign(room: str, expires: int) -> str:
        mac = hmac.new(secret, f"{room}|{expires}".encode(), hashlib.sha256).hexdigest()
        return f"{room}|{expires}|{mac}"

    def board_room(teamloop_board: Optional[str] = Cookie(default=None),
                   authorization: Optional[str] = Header(default=None),
                   x_ccbridge_room: Optional[str] = Header(default=None),
                   x_ccbridge_session: Optional[str] = Header(default=None)) -> str:
        if teamloop_board:
            room, _, rest = teamloop_board.partition("|")
            expires, _, _ = rest.partition("|")
            if expires.isdigit() and int(expires) > time.time() and hmac.compare_digest(
                    teamloop_board, _sign(room, int(expires))):
                return room
        if demo_room and not authorization:  # public demo: read the demo room's board, never write
            return demo_room
        return caller(authorization, x_ccbridge_room, x_ccbridge_session).room

    @app.post("/v1/board/login")
    def board_login(req: BoardLogin, response: Response) -> dict:
        if not ROOM_RE.match(req.room):
            raise HTTPException(400, "Invalid room name")
        from .relay import _hash_token  # same hashing as the relay's room tokens

        with lock:
            row = conn.execute("SELECT token_hash FROM rooms WHERE room = ?", (req.room,)).fetchone()
        if row is None or not hmac.compare_digest(row["token_hash"], _hash_token(req.token)):
            raise HTTPException(403, "Unknown room or wrong token")
        expires = int(time.time()) + COOKIE_DAYS * 86400
        response.set_cookie(COOKIE, _sign(req.room, expires), max_age=COOKIE_DAYS * 86400, httponly=True,
                            samesite="strict", secure=os.getenv("HUB_SECURE_COOKIE", "1") != "0")
        return {"ok": True, "room": req.room}

    # ---- events in ----------------------------------------------------------------------------
    @app.post("/v1/events")
    def post_events(body: EventsIn, who=Depends(caller)) -> dict:
        now, rows = time.time(), []
        with lock:
            allowed = posts.allow(f"{who.room}\0{who.display_name}", now)
        if not allowed:
            raise HTTPException(429, "Too many event batches; the connector will retry")
        for e in body.events:
            if "local" in e:
                raise HTTPException(400, "Events must not carry 'local': that text never leaves the laptop")
            if not ID_RE.match(str(e.get("id", ""))) or not KIND_RE.match(str(e.get("kind", ""))):
                raise HTTPException(422, "Each event needs a 32-hex id and a lowercase kind")
            task = e.get("task") if TASK_RE.match(str(e.get("task") or "")) else None
            e = {**clean(e), "member": who.display_name, "task": task}  # the session says who, not the body
            stored = json.dumps(e, ensure_ascii=False)
            if len(stored.encode()) > MAX_EVENT_BYTES:
                raise HTTPException(413, f"An event is over {MAX_EVENT_BYTES} bytes")
            rows.append((e["id"], who.room, who.display_name, task, e["kind"], str(e.get("ts", ""))[:32], stored, now))
        with lock:
            accepted = sum(conn.execute("INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)", r).rowcount
                           for r in rows)
            conn.commit()
        return {"accepted": accepted, "duplicates": len(rows) - accepted}

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
        out = []
        for t in tasks:
            evs = events_for(room, t["task"], 200)
            titles = [e["facts"].get("title") for e in evs if e.get("kind") == "task_start" and e.get("facts", {}).get("title")]
            if not titles:  # no task_start title (e.g. Codex without MCP): fall back to the branch, T-7-multiply -> "Multiply"
                branch = next((e["branch"] for e in reversed(evs) if (e.get("branch") or "").startswith(t["task"] + "-")), "")
                words = branch[len(t["task"]) + 1:].replace("-", " ").replace("_", " ").strip()
                titles = [words[:1].upper() + words[1:]] if words else []
            snap = latest_snapshot(room, t["task"])
            last_block = max((e["ts"] for e in evs if e["kind"] == "blocked"), default="")
            last_move = max((e["ts"] for e in evs if e["kind"] in ("self_report", "turn_end") and e.get("status") != "blocked"),
                            default="")
            gh = {k: [e for e in evs if e["kind"] == k] for k in ("pr", "review", "check")}
            pr = gh["pr"][-1]["facts"] if gh["pr"] else None
            if last_block and last_block >= last_move:
                status = "blocked"
            elif pr and pr.get("state") == "merged":
                status = "done"
            elif pr and pr.get("state") == "open" and not pr.get("draft"):
                status = "review"
            else:
                status = (snap or {}).get("status", "in_progress")
            out.append({
                "task": t["task"], "title": titles[-1] if titles else "", "events": t["n"],
                "members": sorted({e["member"] for e in evs if e["member"] != "github"}),
                "tools": sorted({e["tool"] for e in evs if e.get("tool")}),
                "pr": pr and {**pr, "checks": gh["check"][-1]["facts"].get("conclusion") if gh["check"] else None,
                              "review": gh["review"][-1]["facts"].get("state") if gh["review"] else None},
                "last_activity": t["last"], "status": status, "progress": snap,
                "recent": [{"id": e["id"], "ts": e.get("ts"), "member": e["member"], "line": progress.describe(e)}
                           for e in evs[-12:] if progress.describe(e)],
            })
        return {"room": room, "generated_at": now, "tasks": out, "demo": room == demo_room,
                "members": [{"name": m["member"], "last_activity": m["last"], "active": now - m["last"] < ACTIVE_SECONDS}
                            for m in members]}

    @app.get("/v1/board")
    def board(room: str = Depends(board_room)) -> dict:
        return build_board(room)

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
            titles = [e["facts"].get("title") for e in evs if e.get("kind") == "task_start" and e.get("facts", {}).get("title")]
            try:
                snap = progress.estimate(row["task"], evs, titles[-1] if titles else "", chat=chat)
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
