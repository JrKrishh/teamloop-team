"""Agent S, job 5: a coding turn's one-line summary for the team, from the agent's last message (PLAN.md §10.1).

The connector sends the message (redacted on the laptop) with the turn's structured facts; the hub answers with the
summary and keeps neither. Nemotron Lightning: it's short, and it runs for every turn."""

from __future__ import annotations

import json
from typing import Callable

from agent_s import llm

STATUSES = ["progress", "blocked", "done", "question"]
MAX = 160
SYSTEM = (  # the same words as the connector's summarize.py, for a local model; keep the two alike
    "You write one-line status updates for a software team lead. You get the final message an AI coding agent "
    "wrote at the end of its turn, plus structured facts. Reply with JSON: summary (at most 160 characters, past "
    "tense, plain English: what got done or what is stuck; no code, no file contents, no secrets, no people's "
    "names) and status (progress, blocked, done, or question: the agent is waiting on the human)."
)
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["summary", "status"],
          "properties": {"summary": {"type": "string"}, "status": {"type": "string", "enum": STATUSES}}}


def summarize(text: str, facts: dict, chat: Callable = llm.chat_json) -> dict:
    """{"summary", "status", "model"}. Raises when the model fails or says nothing; the connector keeps the event."""
    raw = chat("summary", [{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": f"Agent's message:\n{text[:6000]}\n\nFacts: {json.dumps(facts)[:1500]}"}],
               SCHEMA)
    summary = " ".join(str(raw.get("summary", "")).split())
    if not summary:
        raise ValueError("empty summary")
    if len(summary) > MAX:
        summary = summary[: MAX - 1] + "…"
    status = raw.get("status") if raw.get("status") in STATUSES else "progress"
    return {"summary": summary, "status": status, "model": llm.model_for("summary")}
