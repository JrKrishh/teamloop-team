"""Agent S, job 3: the lead's daily digest (PLAN.md §10.1, S2). Big model (Nemotron Ultra on Token Factory).

Same honesty rule as the other jobs: every line cites events; lines citing nothing real are dropped and counted.
"""

from __future__ import annotations

import re
from typing import Callable

from agent_s import llm, qa

SYSTEM = """You are Agent S. Write a software team lead's daily digest from the last day of the team's coding sessions.
The timeline is grouped by task; each line has an event id (e1, e2, ...).
Sections:
- headline: one sentence on the day.
- shipped: work that is finished with proof (a merged PR, or passing tests plus a commit).
- in_progress: work moving forward.
- blocked: work that can't move (a BLOCKED line, a repeated failure, waiting on a human).
- at_risk: work that may slip (no progress for a long time, failing CI, the agent's claims running ahead of the evidence).
Rules: every item cites the event ids that show it; no evidence, no item. One short phrase per item, naming the task id.
"agent says" lines are the coding agent's claims, not proof. Describe work, never judge people."""
ITEM = {"type": "object", "additionalProperties": False, "required": ["text", "evidence"],
        "properties": {"text": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}}}
SECTIONS = ("shipped", "in_progress", "blocked", "at_risk")
TASK = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b")
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["headline", *SECTIONS],
          "properties": {"headline": {"type": "string"}, **{s: {"type": "array", "items": ITEM} for s in SECTIONS}}}


def digest(events: list[dict], chat: Callable = llm.chat_json) -> dict:
    text, ids = qa.context(events)
    if not ids:
        return {"headline": "No coding-session activity in this period.", **{s: [] for s in SECTIONS},
                "dropped_uncited": 0, "model": None}
    raw = chat("digest", [{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": f"Timeline (last 24 hours):\n{text}"}], SCHEMA)
    out: dict = {"headline": " ".join(str(raw.get("headline", "")).split())[:200]}
    dropped = 0
    for section in SECTIONS:
        kept = []
        for item in raw.get(section, []) or []:
            real = [ids[x] for x in item.get("evidence", []) if x in ids]
            words = " ".join(str(item.get("text", "")).split())[:140]
            if real and words:
                kept.append({"text": words, "evidence_ids": real[:5]})
            else:
                dropped += 1
        out[section] = kept[:8]
    # A task is in one place: blocked or shipped wins over in progress.
    settled = {m.group(0) for s in ("blocked", "shipped") for i in out[s] for m in [TASK.search(i["text"])] if m}
    out["in_progress"] = [i for i in out["in_progress"] if not ((m := TASK.search(i["text"])) and m.group(0) in settled)]
    out.update(dropped_uncited=dropped, model=llm.model_for("digest"))
    return out
