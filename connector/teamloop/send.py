"""`teamloop send` / `teamloop daemon`: spool -> summaries -> hub. The one place data leaves the laptop.

Only `spool.public()` records go out, so `local` text can't. Turn-end text is summarized first, and only the
summary is attached. The hub API contract is in docs/hub-api.md.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Callable

from teamloop import spool, summarize

BATCH = 50
MAX_BATCH_BYTES = 48_000  # the hub (ccbridge relay) refuses bodies over 64 KB
SUMMARIZED = ("turn_end", "subagent_end")


def config() -> dict | None:
    path = spool.home() / "config.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def prepare(record: dict, summarizer: Callable | None = None) -> dict:
    summarizer = summarizer or summarize.summarize  # looked up per call, so it can be swapped
    out = spool.public(record)
    text = (record.get("local") or {}).get("text") or ""
    if record.get("kind") in SUMMARIZED and text.strip():
        try:
            s = summarizer(text, record.get("facts") or {})
        except Exception as e:  # noqa: BLE001 - a missing summary must not hold up the rest of the spool
            out["summary_error"] = type(e).__name__
        else:
            if s:
                out.update(summary=s["summary"], status=s["status"], summary_model=s.get("model"))
    return out


def _post(cfg: dict, events: list[dict]) -> None:
    from teamloop import login

    login.request(cfg, "POST", "/v1/events", {"events": events})


def send_once(post: Callable = _post, summarizer: Callable | None = None) -> tuple[int, str | None]:
    """Send one batch. Returns (events sent, error or None). Files are deleted only after the hub accepts them."""
    cfg = config()
    if not cfg:
        return 0, "not connected to a hub yet (teamloop login)"
    paths: list[Path] = spool.pending()[:BATCH]
    if not paths:
        return 0, None
    try:
        events, used, size = [], [], 0
        for p in paths:  # stay under the relay's 64 KB body limit, or one big batch would retry forever
            event = {**prepare(spool.read(p), summarizer), "member": cfg.get("name")}
            n = len(json.dumps(event, ensure_ascii=False).encode())
            if events and size + n > MAX_BATCH_BYTES:
                break
            events.append(event)
            used.append(p)
            size += n
        post(cfg, events)
    except Exception as e:  # noqa: BLE001 - keep the spool, report, retry later
        return 0, f"{type(e).__name__}: {e}"[:200]
    for p in used:
        p.unlink(missing_ok=True)
    return len(used), None


def my_turn(stale: float = 30.0) -> bool:
    """One sender per laptop. sender.lock holds the sender's pid; its mtime is that sender's heartbeat.
    A lost race only means a batch is sent twice, which the hub dedupes by event id."""
    lock, me = spool.home() / "sender.lock", str(os.getpid())
    try:
        holder, age = lock.read_text(), time.time() - lock.stat().st_mtime
    except OSError:
        holder, age = None, 0.0
    if holder not in (None, me) and age < stale:
        return False
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(me)
    return True


def daemon(every: float = 5.0, log: Callable = print, stop: threading.Event | None = None) -> int:
    """Send until stopped. Runs as `teamloop daemon`, or as a thread inside the MCP server (see mcp_server.main)."""
    wait = stop.wait if stop else time.sleep
    backoff, last_err = every, None
    while not (stop and stop.is_set()):
        if not my_turn():
            wait(every)
            continue
        sent, err = send_once()
        if err and err != last_err:
            log(f"{time.strftime('%H:%M:%S')} {err}")
        if sent:
            log(f"{time.strftime('%H:%M:%S')} sent {sent}")
        backoff = min(backoff * 2, 300) if err else every
        last_err = err
        wait(0 if sent == BATCH else backoff)
    return 0


def main(once: bool) -> int:
    if not once:
        return daemon()
    total = 0
    while True:
        sent, err = send_once()
        total += sent
        if err or sent < BATCH:
            print(f"sent {total}" + (f"; stopped: {err}" if err else ""))
            return 1 if err else 0
