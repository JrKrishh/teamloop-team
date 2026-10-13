"""Token usage per turn, read from the coding agent's own transcript on this laptop. Only numbers leave: tokens by
kind, the model's name and how many model calls; never the transcript's text, or its path.

- Claude Code writes each request's usage on its assistant lines, repeated once per content block, so a request is
  counted once by (message id, request id). Subagents write their own files under <session>/subagents/.
- Codex keeps a running total per session in token_count events; a turn is the difference since the last turn.

Each turn reads only what was appended since the last one (an offset per file in ~/.teamloop/usage/), so the hook
stays fast on long sessions. A session TeamLoop saw start counts from that point; one already running counts from
the last TAIL bytes (Codex: from its running total).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path

from teamloop import spool

TAIL = 2_000_000
KEEP_SECONDS = 14 * 86400
FIELDS = ("in", "cw", "cr", "out", "calls")  # fresh input, cache writes, cache reads, output, model calls


def _dir() -> Path:
    return spool.home() / "usage"


def _state_file(path: str) -> Path:
    return _dir() / (hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:20] + ".json")


def _load(path: str) -> dict:
    try:
        return json.loads(_state_file(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(path: str, state: dict) -> None:
    f = _state_file(path)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({**state, "at": time.time()}), encoding="utf-8")
    os.replace(tmp, f)


def _prune() -> None:
    cutoff = time.time() - KEEP_SECONDS
    for f in _dir().glob("*.json") if _dir().is_dir() else []:
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def _new_lines(path: Path, state: dict) -> tuple[list[bytes], int]:
    """Complete lines appended since state['offset'] (a partly written last line waits for next time)."""
    size = path.stat().st_size
    start = state.get("offset")
    fresh = start is None or start > size  # unknown, or the file was rewritten
    if fresh:
        start = max(0, size - TAIL)
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read(size - start)
    if fresh and start > 0:  # began mid-file: skip the partial first line
        cut = data.find(b"\n") + 1
        data, start = data[cut:], start + cut
    end = data.rfind(b"\n") + 1
    return data[:end].splitlines(), start + end


def started(tool: str, transcript: str) -> None:
    """SessionStart: count this session from here on."""
    p = Path(transcript)
    if p.is_file():
        state = {"offset": p.stat().st_size, "since": time.time()}
        if tool == "codex":
            state["total"] = _codex_total(p, {})[0] or {}
        _save(transcript, state)
    _prune()


def _claude_file(path: Path, totals: Counter, models: Counter) -> None:
    state = _load(str(path))
    lines, offset = _new_lines(path, state)
    seen = list(state.get("seen") or [])
    known = set(seen)
    for raw in lines:
        if b'"usage"' not in raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        msg = d.get("message") if isinstance(d.get("message"), dict) else {}
        u = msg.get("usage")
        if d.get("type") != "assistant" or not isinstance(u, dict) or msg.get("model") == "<synthetic>":
            continue
        key = f"{msg.get('id')}:{d.get('requestId')}"
        if key in known:
            continue
        known.add(key)
        seen.append(key)
        out = int(u.get("output_tokens") or 0)
        totals.update({"in": int(u.get("input_tokens") or 0), "cw": int(u.get("cache_creation_input_tokens") or 0),
                       "cr": int(u.get("cache_read_input_tokens") or 0), "out": out, "calls": 1})
        models[msg.get("model") or "claude"] += out + 1
    _save(str(path), {**state, "offset": offset, "seen": seen[-400:]})


def claude(transcript: str) -> dict | None:
    """This turn's usage: the main transcript plus the subagents that ran during the turn."""
    main = Path(transcript)
    if not main.is_file():
        return None
    totals, models = Counter(), Counter()
    previous = _load(transcript)
    since = previous.get("at") or previous.get("since") or time.time() - 900
    _claude_file(main, totals, models)
    subagents = main.with_suffix("") / "subagents"
    if subagents.is_dir():
        for f in sorted(subagents.glob("*.jsonl")):
            if f.stat().st_mtime >= since - 5:
                _claude_file(f, totals, models)
    return _result(totals, models.most_common(1)[0][0] if models else None)


def _codex_total(path: Path, state: dict) -> tuple[dict | None, int, int]:
    """The session's latest running total in the new lines, how many model calls added to it, and the new offset."""
    lines, offset = _new_lines(path, state)
    latest, calls = None, 0
    for raw in lines:
        if b'"token_count"' not in raw:
            continue
        try:
            payload = json.loads(raw).get("payload") or {}
        except (ValueError, AttributeError):
            continue
        total = (payload.get("info") or {}).get("total_token_usage") if payload.get("type") == "token_count" else None
        if isinstance(total, dict):
            latest, calls = total, calls + 1
    return latest, calls, offset


def codex(transcript: str, model: str | None) -> dict | None:
    p = Path(transcript)
    if not p.is_file():
        return None
    state = _load(transcript)
    latest, calls, offset = _codex_total(p, state)
    if latest is None:
        _save(transcript, {**state, "offset": offset})
        return None
    before = state.get("total") or {}
    if int(latest.get("total_tokens") or 0) < int(before.get("total_tokens") or 0):
        before = {}  # a new or rewritten session file
    d = {k: max(0, int(latest.get(k) or 0) - int(before.get(k) or 0))
         for k in ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens")}
    _save(transcript, {**state, "offset": offset, "total": latest})
    totals = Counter({"in": max(0, d["input_tokens"] - d["cached_input_tokens"]), "cw": d["cache_write_input_tokens"],
                      "cr": d["cached_input_tokens"], "out": d["output_tokens"], "calls": calls})
    return _result(totals, model or "codex")


def _result(totals: Counter, model: str | None) -> dict | None:
    if not any(totals[k] for k in FIELDS):
        return None
    return {"model": (model or "")[:60], **{k: int(totals[k]) for k in FIELDS}}


def for_turn(tool: str, payload: dict) -> dict | None:
    transcript = payload.get("transcript_path")
    if not transcript:
        return None
    if tool == "claude_code":
        return claude(transcript)
    if tool == "codex":
        return codex(transcript, payload.get("model"))
    return None
