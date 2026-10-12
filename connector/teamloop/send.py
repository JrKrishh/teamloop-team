"""`teamloop send` / `teamloop daemon`: spool -> summaries -> hub. The one place data leaves the laptop.

Only `spool.public()` records go out, so `local` text can't. Turn-end text is summarized first, and only the
summary is attached. The hub API contract is in docs/hub-api.md.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from teamloop import spool, summarize

BATCH = 50
SUMMARIZED = ("turn_end", "subagent_end")


def config() -> dict | None:
    path = spool.home() / "config.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def prepare(record: dict, summarizer: Callable = summarize.summarize) -> dict:
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


def _post(url: str, token: str, events: list[dict]) -> None:
    req = urllib.request.Request(url, json.dumps({"events": events}).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        if r.status >= 300:
            raise urllib.error.HTTPError(url, r.status, "hub refused the batch", r.headers, None)


def send_once(post: Callable = _post, summarizer: Callable = summarize.summarize) -> tuple[int, str | None]:
    """Send one batch. Returns (events sent, error or None). Files are deleted only after the hub accepts them."""
    cfg = config()
    if not cfg:
        return 0, "not connected to a hub yet (teamloop login)"
    paths: list[Path] = spool.pending()[:BATCH]
    if not paths:
        return 0, None
    try:
        events = [{**prepare(spool.read(p), summarizer), "member": cfg.get("member")} for p in paths]
        post(cfg["hub"].rstrip("/") + "/v1/events", cfg["token"], events)
    except Exception as e:  # noqa: BLE001 - keep the spool, report, retry later
        return 0, f"{type(e).__name__}: {e}"[:200]
    for p in paths:
        p.unlink(missing_ok=True)
    return len(paths), None


def daemon(every: float = 5.0) -> int:
    backoff = every
    while True:
        sent, err = send_once()
        if err:
            print(time.strftime("%H:%M:%S"), err, flush=True)
            backoff = min(backoff * 2, 300)
        else:
            if sent:
                print(time.strftime("%H:%M:%S"), f"sent {sent}", flush=True)
            backoff = every
        time.sleep(0 if sent == BATCH else backoff)


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
