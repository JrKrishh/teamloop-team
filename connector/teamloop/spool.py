"""Local spool: one JSON file per event, written atomically, so parallel hooks never interleave.

`local` holds text that never leaves the laptop. Anything bound for the hub goes through `public()`.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("TEAMLOOP_HOME") or Path.home() / ".teamloop")


def spool_dir() -> Path:
    return home() / "spool"


def paused() -> bool:
    return (home() / "paused").exists()


def append(record: dict) -> Path:
    d = spool_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{time.time_ns()}-{record['id'][:8]}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return path


def pending() -> list[Path]:
    d = spool_dir()
    return sorted(d.glob("*.json")) if d.is_dir() else []


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def public(record: dict) -> dict:
    """The only shape that may leave the laptop: everything except `local`."""
    return {k: v for k, v in record.items() if k != "local"}
