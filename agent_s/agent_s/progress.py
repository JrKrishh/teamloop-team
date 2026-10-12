"""Agent S, job 1: one task's events -> an honest progress snapshot (PLAN.md §10.1-10.2).

Honesty lives in code, not only in the prompt:
- the model sees short event ids (e1, e2...) and must cite them for every item;
- items citing nothing real are dropped and counted (`dropped_uncited`, the eval's "uncited claims");
- the agent's own percent is shown separately as "agent says", never merged into the estimate.
"""

from __future__ import annotations

import time
from typing import Callable

from agent_s import llm

SYSTEM = """You are Agent S. You track progress for a software team lead.
You get one task and the timeline of events from the developer's AI coding session(s).
Rules:
1. Every item you write must cite the event ids (e1, e2, ...) that show it. If nothing shows it, leave it out.
2. Lines marked "agent says" are the coding agent's own claims, not proof. Passing tests, commits, PRs and CI count more.
3. Fill done, doing, next and blockers first. Then set percent for the whole TASK from this scale:
   0-10 started, nothing built yet | 10-40 code written, not tested yet | 40-70 core works, some tests pass |
   70-90 tests pass, polish or review left | 90-100 finished: tests pass AND committed (or a PR is open).
   Don't copy the agent's number; place the task on the scale from the evidence.
4. blockers: only things stopping progress now, and each needs an event that shows it: a "BLOCKED" line,
   the same failure twice with no fix in between, or the agent waiting for its human. Planned next steps are not blockers.
5. Describe the work, never judge the person. Short phrases, at most 12 words each."""

ITEM = {"type": "object", "additionalProperties": False, "required": ["text", "evidence"],
        "properties": {"text": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}}}
# Property order is generation order: evidence lists first, the number last.
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["done", "doing", "next", "blockers", "percent", "confidence"],
          "properties": {"done": {"type": "array", "items": ITEM}, "doing": {"type": "array", "items": ITEM},
                         "next": {"type": "array", "items": ITEM}, "blockers": {"type": "array", "items": ITEM},
                         "percent": {"type": "integer"}, "confidence": {"type": "string", "enum": ["low", "medium", "high"]}}}


def _clock(ts: str) -> str:
    return ts[11:16] if ts and len(ts) >= 16 else "--:--"


def describe(e: dict) -> str | None:
    """One compact line per event; None for noise (reads, searches)."""
    kind, f, rep = e.get("kind"), e.get("facts") or {}, e.get("report") or {}
    if kind == "session_start":
        return f"{e.get('tool')} session started"
    if kind == "task_start":
        return "task started" + (f": {f['title']}" if f.get("title") else "")
    if kind == "tool":
        cmd = f.get("cmd")
        if cmd:
            counts = ", ".join(f"{cmd[k]} {k}" for k in ("passed", "failed") if cmd.get(k))
            return f"ran {cmd['kind']} command: {'ok' if cmd.get('ok') else 'FAILED'}" + (f" ({counts})" if counts else "")
        if f.get("file"):
            return f"edited {f['file']}" + ("" if f.get("ok", True) else " (failed)")
        if not f.get("ok", True):
            return f"{f.get('tool')} failed" + (f" (exit {f['exit']})" if f.get("exit") is not None else "")
        return None
    if kind in ("turn_end", "subagent_end"):
        if e.get("summary"):
            return f"turn summary [{e.get('status', 'progress')}]: {e['summary']}"
        return "turn ended (no summary)"
    if kind == "self_report":
        parts = [f"agent says {rep.get('percent')}% done"]
        for key in ("done", "next"):
            if rep.get(key):
                parts.append(f"{key}: " + "; ".join(rep[key]))
        if rep.get("doing"):
            parts.append(f"doing: {rep['doing']}")
        return " | ".join(parts)
    if kind == "blocked":
        return f"agent says BLOCKED (needs {rep.get('needs')}): {rep.get('reason')}"
    if kind == "waiting_input":
        return "agent is waiting for its human"
    if kind == "session_end":
        return f"session ended ({f.get('reason')})"
    return f"{kind}: {f}"  # future kinds (commit, pr, check) still show up


def timeline(events: list[dict]) -> tuple[str, dict[str, str]]:
    lines, ids = [], {}
    for e in sorted(events, key=lambda x: x.get("ts", "")):
        text = describe(e)
        if text is None:
            continue
        short = f"e{len(ids) + 1}"
        ids[short] = e["id"]
        lines.append(f"{short} {_clock(e.get('ts', ''))} {text}")
    return "\n".join(lines), ids


def _cited(items: list[dict], ids: dict[str, str], limit: int) -> tuple[list[dict], int]:
    kept, dropped = [], 0
    for item in items or []:
        real = [ids[x] for x in item.get("evidence", []) if x in ids]
        text = " ".join(str(item.get("text", "")).split())[:120]
        if real and text:
            kept.append({"text": text, "evidence_ids": real})
        else:
            dropped += 1
    return kept[:limit], dropped


def estimate(task: str, events: list[dict], title: str = "", chat: Callable = llm.chat_json) -> dict:
    text, ids = timeline(events)
    if not ids:
        return {"task": task, "percent": 0, "confidence": "low", "done": [], "doing": [], "next": [], "blockers": [],
                "status": "todo", "agent_says_percent": None, "dropped_uncited": 0, "model": None}
    raw = chat("progress", [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": f"Task {task}{': ' + title if title else ''}\n\nTimeline:\n{text}"}], SCHEMA)
    out, dropped = {"task": task}, 0
    for key, limit in (("done", 6), ("doing", 1), ("next", 4), ("blockers", 3)):
        out[key], d = _cited(raw.get(key, []), ids, limit)
        dropped += d
    reports = [e for e in events if e.get("kind") == "self_report"]
    out.update(
        percent=max(0, min(100, int(raw.get("percent", 0)))),
        confidence=raw.get("confidence") if raw.get("confidence") in ("low", "medium", "high") else "low",
        status="blocked" if out["blockers"] else "in_progress",
        agent_says_percent=(max(reports, key=lambda e: e.get("ts", ""))["report"].get("percent") if reports else None),
        dropped_uncited=dropped,
        model=llm.model_for("progress"),
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    return out
