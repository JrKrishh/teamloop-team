"""One turn of an agent: a tool-calling loop on this laptop, with Nemotron (through the hub's /v1/llm) as the model.

The mode decides what waits for the person, as in Claude Code: read tools always run; changes ask in Manual, run in
Auto and are queued in Plan (Run plan applies them); shell commands always ask. Each turn streams events to the
window (thinking, text, tool cards with their state, the answer). Chats are kept in ~/.teamloop/chats."""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from teamloop import spool

from . import agents as agent_store
from . import skills as skill_store
from .mcpman import Manager, Tool
from .tools import BY_NAME, BUILTINS, Builtin

MAX_STEPS = 14
TO_MODEL, TO_WINDOW = 12_000, 4_000
BASE = """You are {name}, an agent in Super Agents, the app where a software team sees and plans the work their
developers do with AI coding agents. You work for {person} in the team "{team}" (members: {members}).

Use tools to find things out and to act; don't guess. Claims about what the team did must come from team tools
(team_ask answers with citations); say so when there's no evidence. Keep answers short and concrete.
Mode: {mode}. {mode_rule}"""
MODE_RULES = {
    "manual": "The person approves each change you make; propose changes with tool calls as usual.",
    "auto": "Routine changes run straight away and the person can undo them; shell commands still ask first.",
    "plan": "Nothing changes in plan mode. For each change in your plan, call its tool anyway (create_task, close_task, "
            "write_file, ...): the call is queued as a step for the person to review, and nothing runs until they choose "
            "Run plan. End with a short numbered plan.",
}
# Models often answer plan mode with a plan in prose and too few calls; this asks once for the missing calls (still
# only queued).
PLAN_NUDGE = ("Now queue that plan: call the change tool for each step. In plan mode these calls are only queued for the "
              "person to review; nothing runs yet. If the plan changes nothing, reply with just: No changes.")
PLAN_CHECK = ("Queued so far: {queued}. Queue every step of your plan that isn't queued yet, and don't repeat these. "
              "If every step is queued, reply with just: All queued.")


def chats_dir():
    return spool.home() / "chats"


def load_chat(chat_id: str) -> dict:
    try:
        return json.loads((chats_dir() / f"{chat_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_chat(chat: dict) -> None:
    chats_dir().mkdir(parents=True, exist_ok=True)
    (chats_dir() / f"{chat['id']}.json").write_text(json.dumps(chat), encoding="utf-8")


def list_chats(limit: int = 40) -> list[dict]:
    if not chats_dir().is_dir():
        return []
    out = []
    for f in sorted(chats_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
            out.append({"id": c["id"], "title": c.get("title", ""), "agent": c.get("agent"), "updated": c.get("updated", 0)})
        except (OSError, ValueError, KeyError):
            continue
    return out


@dataclass
class Turn:
    chat: dict
    agent: dict
    message: str
    attachments: list[dict]
    mode: str
    model: str
    hub: Callable          # hub(method, path, body=None) -> dict, team-scoped, raises RuntimeError(detail)
    llm: Callable          # llm(messages, tools, tier) -> {content, tool_calls, model}
    mcp: Manager
    person: str = "you"
    id: str = field(default_factory=lambda: secrets.token_urlsafe(9))
    events: list = field(default_factory=list)
    planned: list = field(default_factory=list)
    done: bool = False

    def __post_init__(self):
        self.cond = threading.Condition()
        self.decisions: dict[str, threading.Event] = {}
        self.answers: dict[str, bool] = {}
        self.cancelled = False
        self.skills = {}
        self.tools: dict[str, Builtin | Tool] = {}

    # ---- events for the window -----------------------------------------------------------------------------
    def emit(self, kind: str, **data) -> None:
        with self.cond:
            self.events.append({"i": len(self.events), "kind": kind, **data})
            self.cond.notify_all()

    def wait(self, after: int, timeout: float = 20) -> list[dict]:
        with self.cond:
            if len(self.events) <= after and not self.done:
                self.cond.wait(timeout)
            return self.events[after:]

    def decide(self, call_id: str, approve: bool) -> None:
        self.answers[call_id] = approve
        if call_id in self.decisions:
            self.decisions[call_id].set()

    def cancel(self) -> None:
        self.cancelled = True
        for ev in self.decisions.values():
            ev.set()

    # ---- the loop --------------------------------------------------------------------------------------------
    def _system(self, board: dict) -> str:
        members = ", ".join(m["name"] for m in board.get("members", [])) or "unknown"
        text = BASE.format(name=self.agent["name"], person=self.person, team=board.get("room", "your team"), members=members,
                           mode=self.mode, mode_rule=MODE_RULES[self.mode])
        on = [self.skills[n] for n in self.agent.get("skills", []) if n in self.skills]
        always = [s for s in on if s.name in skill_store.DEFAULT_ON]
        later = [s for s in on if s.name not in skill_store.DEFAULT_ON]
        for s in always:
            text += f"\n\n## Skill: {s.name} (always on)\n{s.body()}"
        if later:
            text += "\n\n## More skills (read one with load_skill when it fits the task)\n" + "\n".join(f"- {s.name}: {s.description}" for s in later)
        if self.agent.get("instructions", "").strip():
            text += f"\n\n## Your instructions from {self.person}\n{self.agent['instructions'].strip()}"
        return text

    def _toolset(self) -> list[dict]:
        groups = {g for g, on in (self.agent.get("tools") or {}).items() if on} | {"skills"}
        self.tools = {b.name: b for b in BUILTINS if b.group in groups}
        if not self.skills:
            for name in ("load_skill", "read_skill_file"):
                self.tools.pop(name, None)
        schemas = [b.schema() for b in self.tools.values()]
        for t in self.mcp.tools(self.agent.get("connectors") or []):
            self.tools[t.full] = t
            schemas.append({"type": "function", "function": {"name": t.full, "description": t.description, "parameters": t.schema}})
        return schemas

    def _kind(self, tool) -> str:
        if isinstance(tool, Tool):
            return "read" if tool.read_only else "change"
        return tool.kind

    def _execute(self, tool, args: dict) -> tuple[str, bool]:
        if isinstance(tool, Tool):
            return self.mcp.call(tool, args)
        return str(tool.run(self, **args)), False

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 - shown in the chat
            self.emit("error", text=f"{e}"[:500] or type(e).__name__)
        finally:
            self.done = True
            self.emit("end", planned=len(self.planned))

    def _run(self) -> None:
        self.skills = skill_store.all_skills()
        board = self.hub("GET", "board")
        tools = self._toolset()
        self.emit("start", agent={k: self.agent[k] for k in ("id", "name", "color")}, mode=self.mode, model=self.model,
                  tools=len(tools), mcp_errors=dict(self.mcp.errors))
        content = self.message + "".join(f"\n\n[Imported file: {a['name']}]\n{a['text'][:60_000]}" for a in self.attachments)
        history = self.chat.get("messages", [])[-24:]
        messages = [{"role": "system", "content": self._system(board)}, *history, {"role": "user", "content": content}]
        used, answer, model, plan_text = [], "", "", ""
        for _ in range(MAX_STEPS):
            if self.cancelled:
                answer = answer or "Stopped."
                break
            self.emit("thinking")
            step = self.llm(messages, tools, self.model)
            model = step.get("model", model)
            calls = step.get("tool_calls") or []
            if step.get("content") and calls:
                self.emit("text", text=step["content"])
            if not calls:
                text = (step.get("content") or "").strip()
                if self.mode == "plan" and not plan_text and text:
                    plan_text = text
                    queued = "; ".join(f"{t.name if isinstance(t, Builtin) else t.full} {json.dumps(a)}" for _, t, a in self.planned)
                    nudge = PLAN_CHECK.format(queued=queued) if queued else PLAN_NUDGE
                    messages += [{"role": "assistant", "content": text}, {"role": "user", "content": nudge}]
                    continue
                answer = plan_text or text or "Done."
                break
            messages.append({"role": "assistant", "content": step.get("content") or "", "tool_calls": calls})
            for call in calls:
                result = self._one(call)
                used.append(call["function"]["name"])
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result[:TO_MODEL]})
        else:
            answer = answer or "I stopped after many steps. Ask me to continue if you need more."
        self.emit("answer", text=answer, model=model)
        self._remember(content, answer, used)

    def _one(self, call: dict) -> str:
        cid, name = call.get("id") or secrets.token_hex(4), call["function"]["name"]
        tool = self.tools.get(name)
        try:
            args = json.loads(call["function"].get("arguments") or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be an object")
        except ValueError as e:
            self.emit("tool", id=cid, name=name, args={}, status="failed", result=f"Bad arguments: {e}")
            return f"Error: the arguments were not valid JSON ({e})."
        if not tool:
            self.emit("tool", id=cid, name=name, args=args, status="failed", result="No such tool")
            return f"Error: there is no tool called {name}."
        kind = self._kind(tool)
        group = tool.group if isinstance(tool, Builtin) else f"mcp:{tool.connector}"
        card = {"id": cid, "name": name, "args": args, "access": kind, "group": group}
        if kind != "read" and self.mode == "plan":
            self.planned.append((cid, tool, args))
            self.emit("tool", **card, status="planned")
            return "Not run: plan mode. This change is part of the plan the person will review and run."
        if kind == "ask" or (kind == "change" and self.mode == "manual"):
            ev = self.decisions[cid] = threading.Event()
            self.emit("tool", **card, status="asking")
            ev.wait()
            if self.cancelled or not self.answers.get(cid):
                self.emit("tool", **card, status="declined")
                return "The person declined this action. Don't retry it; ask or continue without it."
        self.emit("tool", **card, status="running")
        try:
            result, is_error = self._execute(tool, args)
        except Exception as e:  # noqa: BLE001 - the model sees the error and can adjust
            result, is_error = f"Error: {e}", True
        extra = {}
        if name == "team_ask":
            try:
                extra["citations"] = json.loads(result).get("citations", [])
            except ValueError:
                pass
        self.emit("tool", **card, status="failed" if is_error else "done", result=result[:TO_WINDOW], **extra)
        return result

    def run_plan(self) -> None:
        """Apply the changes queued in plan mode, in order."""
        planned, self.planned = self.planned, []
        self.done = False
        try:
            for cid, tool, args in planned:
                card = {"id": cid, "name": tool.name if isinstance(tool, Builtin) else tool.full, "args": args,
                        "access": self._kind(tool), "group": tool.group if isinstance(tool, Builtin) else f"mcp:{tool.connector}"}
                self.emit("tool", **card, status="running")
                try:
                    result, is_error = self._execute(tool, args)
                except Exception as e:  # noqa: BLE001
                    result, is_error = f"Error: {e}", True
                self.emit("tool", **card, status="failed" if is_error else "done", result=result[:TO_WINDOW])
        finally:
            self.done = True
            self.emit("end", planned=0)

    def _remember(self, content: str, answer: str, used: list[str]) -> None:
        chat = self.chat
        chat.setdefault("messages", []).extend([
            {"role": "user", "content": content[:20_000]},
            {"role": "assistant", "content": answer + (f"\n\n(tools used: {', '.join(sorted(set(used)))})" if used else "")}])
        chat.setdefault("view", []).append({"user": self.message, "files": [a["name"] for a in self.attachments],
                                            "answer": answer, "agent": self.agent["id"], "mode": self.mode,
                                            "events": [e for e in self.events if e["kind"] in ("tool", "text")][-60:]})
        chat["title"] = chat.get("title") or self.message[:60]
        chat["agent"] = self.agent["id"]
        chat["updated"] = time.time()
        save_chat(chat)


def new_chat(agent_id: str) -> dict:
    return {"id": secrets.token_urlsafe(8), "agent": agent_id, "created": time.time(), "messages": [], "view": []}


def get_agent(agent_id: str) -> dict:
    return agent_store.get(agent_id)
