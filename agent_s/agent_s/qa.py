"""Agent S, job 2: the lead asks, Agent S answers from cited events or says it doesn't know (PLAN.md US-6).

No embeddings (decision D7): a small team's recent events fit in one prompt, grouped by task.
An answer with no valid citation is replaced, in code, by "no evidence yet".
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Callable

from agent_s import llm, progress

MAX_EVENTS = 400
NO_EVIDENCE = "I don't have evidence for that yet."
_SHORT_IDS = re.compile(r"\s*\(\s*e\d+(?:\s*,\s*e\d+)*\s*\)|\s*\be\d+\b")  # "(e6, e9)": citations travel separately
SYSTEM = """You are Agent S. You answer a software team lead's questions about the team's work.
You get the recent timeline of every task, grouped by task, from the developers' AI coding sessions.
Rules:
1. Answer only from the timeline. Cite the event ids (e1, e2, ...) that support the answer.
2. First decide answerable. true: the question is about coding work the timeline records (edits, tests, commits,
   blocks, who works on what), including "not yet" (no test events on a task means it hasn't been tested).
   false: things coding sessions don't record (deploys, meetings, reviews, plans). Then answer and cite the
   1-5 events that matter most. If not answerable, say "No evidence in the timeline" and list what is unknown.
3. "agent says" lines are the coding agent's own claims; say "the agent reports" when you rely on one.
4. At most 3 sentences. Talk about tasks and work, never judge a person."""
# Property order is generation order: decide answerability before writing an answer.
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answerable", "answer", "citations", "unknowns"],
          "properties": {"answerable": {"type": "boolean"}, "answer": {"type": "string"},
                         "citations": {"type": "array", "items": {"type": "string"}},
                         "unknowns": {"type": "array", "items": {"type": "string"}}}}


def context(events: list[dict]) -> tuple[str, dict[str, str]]:
    recent = sorted(events, key=lambda e: e.get("ts", ""))[-MAX_EVENTS:]
    by_task: dict[str, list[dict]] = defaultdict(list)
    for e in recent:
        by_task[e.get("task") or "(no task)"].append(e)
    blocks, ids = [], {}
    for task, evs in by_task.items():
        people = sorted({e.get("member") for e in evs if e.get("member")})
        lines = []
        for e in evs:
            text = progress.describe(e)
            if text is None:
                continue
            short = f"e{len(ids) + 1}"
            ids[short] = e["id"]
            lines.append(f"{short} {progress._clock(e.get('ts', ''))} {text}")
        if lines:
            blocks.append(f"## {task} (worked on by {', '.join(people) or 'unknown'})\n" + "\n".join(lines))
    return "\n\n".join(blocks), ids


def answer(question: str, events: list[dict], chat: Callable = llm.chat_json) -> dict:
    text, ids = context(events)
    if not ids:
        return {"answer": NO_EVIDENCE, "citations": [], "unknowns": ["no activity recorded yet"], "model": None}
    raw = chat("qa", [{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": f"Timeline:\n{text}\n\nLead's question: {question}"}], SCHEMA)
    cited = [ids[c] for c in raw.get("citations", []) if c in ids][:5]
    reply = " ".join(_SHORT_IDS.sub("", str(raw.get("answer", ""))).split())
    unknowns = [" ".join(str(u).split())[:120] for u in raw.get("unknowns", [])][:5]
    says_none = re.match(r"\s*(no evidence|i don'?t have evidence)", reply, re.I)  # the text and citations must agree
    if not raw.get("answerable", True) or not cited or says_none:  # grounded or nothing
        cited = []
        reply = NO_EVIDENCE + (f" Unknown: {'; '.join(unknowns)}." if unknowns else "")
    return {"answer": reply, "citations": cited, "unknowns": unknowns, "model": llm.model_for("qa")}
