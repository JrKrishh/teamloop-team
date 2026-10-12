"""Seed the public demo room from demo/demo.json (built by scripts/build_demo.py with the real Agent S).
Timestamps are shifted so the newest event is a few minutes old whenever the hub starts."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI

DATA = Path(__file__).parent / "demo" / "demo.json"


def seed(app: FastAPI, room: str) -> int:
    conn, lock = app.state.conn, app.state.lock
    with lock:
        if conn.execute("SELECT 1 FROM events WHERE room = ? LIMIT 1", (room,)).fetchone():
            return 0
    data = json.loads(DATA.read_text(encoding="utf-8"))
    now = time.time()
    rows = []
    for e in data["events"]:
        e = dict(e)
        at = now - e.pop("offset_min") * 60
        e["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(at)) + ".000Z"
        rows.append((e["id"], room, e["member"], e["task"], e["kind"], e["ts"], json.dumps(e, ensure_ascii=False), at))
    with lock:
        conn.executemany("INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        conn.executemany("INSERT INTO snapshots VALUES (?, ?, ?, ?)",
                         [(room, task, now, json.dumps(snap, ensure_ascii=False)) for task, snap in data["snapshots"].items()])
        conn.commit()
    return len(rows)
