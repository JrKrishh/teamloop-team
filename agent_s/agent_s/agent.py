"""Agent S, job 4: one turn of the Super Agents chat. It answers from the team's timeline with citations (the same
rule as qa: a claim about the work needs evidence), reads any files the person imported, and, when asked, proposes
changes to the board: create, assign, close or start tasks.

Agent S only proposes. The app applies the actions by mode: Plan (review the plan, then run it), Manual (approve each
change) or Auto (apply routine changes and report them). Proposals are checked here, in code: task ids must exist or
be new, owners must be members, at most 12 actions.
"""

from __future__ import annotations

import re
from typing import Callable

from agent_s import llm, qa

ACTIONS = ("create_task", "assign_task", "close_task", "start_task")
MAX_ACTIONS = 12
MAX_FILE_CHARS = 20_000
TASK_ID = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
# "(events e5–e9)", "(see e3 and e7)": citations travel separately, so the whole aside goes, not just the ids
_CITE_ASIDE = re.compile(r"\s*\([^()]*\be\d+\b[^()]*\)")
SYSTEM = """You are Agent S inside Super Agents, the agent for a software team whose developers code with AI agents.
You get the team's members, the board (each task's id, title, status and owner), the recent timeline of the
developers' coding sessions grouped by task (event ids e1, e2, ...), any files the user imported, and the mode.

1. Decide kind. "work": the message asks what the team did, is doing or is stuck on. "plan": it asks you to plan,
   break down, assign, close or start work, or to use an imported file. "other": anything else.
2. Answer in at most 4 sentences. For "work", answer only from the timeline and cite the event ids that show it;
   "agent says" lines are the coding agent's own claims. Never claim progress the timeline doesn't show.
3. For "plan", propose actions; for "work" and "other", propose none unless the user asked for a change.
   - create_task: title (short and imperative), owner (a member name, or "" when unclear), task ("" to number it).
   - assign_task: task id and owner. close_task: task id (done or dropped). start_task: task id and title, to make
     it the task the user works on now.
   Use member names exactly as listed and only tasks on the board or ones you create. Each action has a short why.
4. In plan mode, also write the plan as short numbered steps; otherwise leave plan empty.
Describe work, never judge people."""
ACTION = {"type": "object", "additionalProperties": False, "required": ["type", "task", "title", "owner", "why"],
          "properties": {"type": {"type": "string", "enum": list(ACTIONS)}, "task": {"type": "string"},
                         "title": {"type": "string"}, "owner": {"type": "string"}, "why": {"type": "string"}}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["kind", "answer", "citations", "plan", "actions"],
          "properties": {"kind": {"type": "string", "enum": ["work", "plan", "other"]}, "answer": {"type": "string"},
                         "citations": {"type": "array", "items": {"type": "string"}},
                         "plan": {"type": "array", "items": {"type": "string"}},
                         "actions": {"type": "array", "items": ACTION}}}


def next_id(existing: set[str]) -> str:
    """The next free id in the board's own scheme: T-21 and T-22 on the board -> T-23. Empty board -> T-1."""
    nums: dict[str, int] = {}
    for t in existing:
        prefix, _, n = t.rpartition("-")
        nums[prefix] = max(nums.get(prefix, 0), int(n))
    prefix = max(nums, key=lambda p: (sum(t.startswith(p + "-") for t in existing), nums[p])) if nums else "T"
    return f"{prefix}-{nums.get(prefix, 0) + 1}"


def check_actions(raw: list, board: set[str], members: list[str]) -> list[dict]:
    """Keep the proposals the app can apply: known types, real tasks, real members. Numbers new tasks."""
    who = {m.lower(): m for m in members}
    known, out = set(board), []
    for a in raw or []:
        kind, task = a.get("type"), str(a.get("task") or "").strip().upper()
        title = " ".join(str(a.get("title") or "").split())[:120]
        owner = who.get(str(a.get("owner") or "").strip().lower())
        if kind == "create_task":
            if not title:
                continue
            task = task if TASK_ID.match(task) and task not in known else next_id(known)
        elif kind not in ACTIONS or task not in known:
            continue
        if kind == "assign_task" and not owner:
            continue
        known.add(task)
        out.append({"id": f"a{len(out) + 1}", "type": kind, "task": task, "title": title, "owner": owner,
                    "why": " ".join(str(a.get("why") or "").split())[:160]})
        if len(out) == MAX_ACTIONS:
            break
    return out


def turn(message: str, events: list[dict], board: list[dict], members: list[str], attachments: list[dict] | None = None,
         mode: str = "manual", chat: Callable = llm.chat_json) -> dict:
    """board: [{task, title, status, owner}]; attachments: [{name, text}]. Returns {answer, citations, plan, actions,
    kind, model}; citations are real event ids."""
    timeline, ids = qa.context(events)
    lines = [f"{t['task']} [{t.get('status', '')}] {t.get('title') or ''} (owner: {t.get('owner') or 'none'})" for t in board]
    files = "\n\n".join(f"### {a['name']}\n{a['text'][:MAX_FILE_CHARS]}" for a in attachments or []) or "(none)"
    user = (f"Mode: {mode}\nMembers: {', '.join(members) or '(none)'}\n\nBoard:\n" + ("\n".join(lines) or "(empty)")
            + f"\n\nTimeline:\n{timeline or '(no session events yet)'}\n\nImported files:\n{files}\n\nMessage: {message}")
    raw = chat("agent", [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], SCHEMA)
    cited = [ids[c] for c in raw.get("citations", []) if c in ids][:8]
    answer = " ".join(qa._SHORT_IDS.sub("", _CITE_ASIDE.sub("", str(raw.get("answer", "")))).split())
    kind = raw.get("kind") if raw.get("kind") in ("work", "plan", "other") else "other"
    if kind == "work" and not cited:  # the honesty rule: a claim about the work needs evidence
        answer = qa.NO_EVIDENCE
    actions = check_actions(raw.get("actions"), {t["task"] for t in board}, members)
    plan = [" ".join(str(s).split())[:200] for s in raw.get("plan") or []][:12] if mode == "plan" else []
    return {"answer": answer, "citations": cited, "plan": plan, "actions": actions, "kind": kind,
            "model": llm.model_for("agent")}
