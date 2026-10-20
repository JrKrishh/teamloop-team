"""Turns on the person's own Claude Code or Codex. Picked in the composer's model menu, an agent's turn runs in that
tool's CLI on this laptop: on the model the person picked there lately (teamloop.models), with their own sign-in and
the tool's own tools (TeamLoop's too, where its MCP server is registered). Nothing goes through the hub: no Nemotron,
no hub tokens.

The window gets a Nemotron turn's events, so step cards, Allow/Deny, Run plan and the phone work the same way:
- Claude Code runs in its streaming mode, as its SDK does: the message, and any note typed while it works, go in on
  stdin, and each permission prompt comes back here, where the chat's mode decides it as for the app's own tools
  (Manual asks before a change, Auto runs it, a command always asks) along with the team's rules. Plan is Claude Code's
  own plan mode; Run plan resumes the session to carry the plan out.
- Codex's exec mode can't ask, so Manual and Plan run it in its read-only sandbox and Auto in its workspace-write one;
  a note typed while it works goes in when the run in progress ends.

A chat keeps its CLI session (chat["cli"]), so a follow-up continues it; a new session in a chat that started elsewhere
gets the chat so far in its first message. Messages travel on stdin, never on the command line, where a .cmd shim could
misread them.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from teamloop import claude, codex, models, spool

from .. import store
from .loop import LEAD_RULE, STEER, Turn, chat_project, save_chat
from .superteam import SESSION_ID, _kill_tree

NAMES = {"claude_code": "Claude Code", "codex": "Codex"}
CLIS = {"claude_code": claude.cli, "codex": codex.cli}
CODEX_EFFORT = {"low": "low", "medium": "medium", "high": "high", "max": "high"}
TO_WINDOW, RECAP = 4_000, 6
GONE = re.compile(r"no (conversation|session|saved session|rollout)\b[^\n]*found", re.I)
STEP = re.compile(r"^\s*(\d+[.)]|[-*])\s+\S", re.M)
RULES = {
    "claude_code": {
        "manual": "{person} approves each change before it runs, and every command.",
        "auto": "Changes run straight away; a command asks {person} first.",
        "plan": "Plan only: change nothing. Read what you need, then present your plan; {person} reviews it and runs it.",
    },
    "codex": {
        "manual": "Read only: you can't change files. Say what you'd change; {person} can switch to Auto to let you.",
        "auto": "You may edit files in this repo.",
        "plan": "Plan only: change nothing. Read what you need, then end with a short numbered plan {person} can run.",
    },
}
CARRY_OUT = "{person} ran your plan: carry it out now, then say briefly what you did."
PLAN_KEPT = "The person reviews your plan in Super Agents and runs it from there. Stop here."
# Claude Code's tools as the chat's cards show them: the app's own names where one fits, what each may do there (a read
# runs, a change follows the mode, an ask always asks) and which arguments the card shows, under the app's names
CLAUDE_TOOLS = {
    "Read": ("read_file", "read", {"path": "file_path"}),
    "Write": ("write_file", "change", {"path": "file_path", "content": "content"}),
    "Edit": ("edit_file", "change", {"path": "file_path", "old": "old_string", "new": "new_string"}),
    "MultiEdit": ("edit_file", "change", {"path": "file_path"}),
    "NotebookEdit": ("edit_file", "change", {"path": "notebook_path"}),
    "Bash": ("run_command", "ask", {"command": "command"}),
    "PowerShell": ("run_command", "ask", {"command": "command"}),
    "Grep": ("search_files", "read", {"query": "pattern", "path": "path"}),
    "Glob": ("list_files", "read", {"path": "pattern"}),
    "WebFetch": ("fetch_url", "read", {"url": "url"}),
    "WebSearch": ("web_search", "read", {"query": "query"}),
    "TodoWrite": ("todo", "read", {}),
    "Task": ("subagent", "read", {"task": "description"}),
    "Agent": ("subagent", "read", {"task": "description"}),
    "ExitPlanMode": ("exit_plan", "read", {"plan": "plan"}),
}
# the connector's MCP tools (mcp__teamloop__*), by the app's names for the same things
TEAMLOOP_TOOLS = {
    "get_team_status": ("team_board", "read", {}),
    "read_messages": ("read_messages", "read", {}),
    "team_changes": ("team_changes", "read", {"repo": "repo_name"}),
    "ask_status": ("session_prompt", "read", {"id": "prompt_id"}),
    "message_teammate": ("message_teammate", "change", {"to": "to", "text": "text", "task": "task"}),
    "ask_teammate": ("prompt_session", "change", {"member": "member", "prompt": "question", "task": "task"}),
    "task_start": ("start_task", "change", {"task": "task_id"}),
    "report_progress": ("report_progress", "change", {"doing": "doing", "percent": "percent"}),
    "mark_blocked": ("mark_blocked", "change", {"reason": "reason"}),
    "handoff": ("handoff", "ask", {"task": "task_id", "to": "to", "note": "note"}),
}


def available() -> list[dict]:
    """The coding agents this laptop can run turns on, for the model menus, with the model each would use."""
    out = []
    for tool, name in NAMES.items():
        if CLIS[tool]():
            model = models.current(tool)
            out.append({"id": tool, "label": name, "model": model, "model_label": models.label(model)})
    return out


def repo_path(p: str) -> str:
    """An absolute path inside a connected repo, written as the app writes paths ('acme-web/src/app.ts')."""
    if not p or not Path(p).is_absolute():
        return p
    for r in store.repos():
        try:
            return f"{Path(r).name}/{Path(p).resolve().relative_to(Path(r).resolve()).as_posix()}"
        except (ValueError, OSError):
            continue
    return p


def card_of(name: str, args: dict) -> tuple[str, str, dict, str]:
    """A CLI tool call as a card: (name, kind, arguments to show, group)."""
    if name.startswith("mcp__teamloop__") and name[15:] in TEAMLOOP_TOOLS:
        (card, kind, keys), group = TEAMLOOP_TOOLS[name[15:]], "team"
    elif name in CLAUDE_TOOLS:
        (card, kind, keys), group = CLAUDE_TOOLS[name], "cli"
    else:  # another MCP server's tool, or one of the CLI's this doesn't know: shown as it is, as a change
        server = name.split("__")[1] if name.startswith("mcp__") and name.count("__") >= 2 else ""
        return name, "change", dict(args), f"mcp:{server}" if server else "cli"
    shown = {k: args[v] for k, v in keys.items() if args.get(v) not in (None, "")}
    if "path" in shown:
        shown["path"] = repo_path(str(shown["path"]))
    if name == "TodoWrite":
        shown["steps"] = len(args.get("todos") or [])
    elif name == "MultiEdit":
        shown["edits"] = len(args.get("edits") or [])
    return card, kind, shown, group


def codex_card(item: dict) -> tuple[str, str, dict, str] | None:
    """A Codex item that's a step, as a card; None for its messages and reasoning."""
    kind = item.get("type")
    if kind == "command_execution":
        return "run_command", "ask", {"command": str(item.get("command") or "")}, "cli"
    if kind == "file_change":
        paths = [repo_path(str(c.get("path") or "")) for c in item.get("changes") or [] if isinstance(c, dict)]
        return "edit_file", "change", {"path": paths[0] if paths else "", **({"files": len(paths)} if len(paths) > 1 else {})}, "cli"
    if kind == "mcp_tool_call":
        return card_of(f"mcp__{item.get('server')}__{item.get('tool')}",
                       item["arguments"] if isinstance(item.get("arguments"), dict) else {})
    if kind == "web_search":
        return "web_search", "read", {"query": str(item.get("query") or "")}, "cli"
    if kind == "todo_list":
        return "todo", "read", {"steps": len(item.get("items") or [])}, "cli"
    return None


def _text(content) -> str:
    """A tool result as text: Claude Code sends a string or a list of blocks."""
    if isinstance(content, list):
        return "\n".join(str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return str(content or "")


class SessionGone(Exception):
    """The chat's CLI session isn't on this laptop any more: a new one starts."""


class CliTurn(Turn):
    """A turn whose model is the person's Claude Code or Codex (self.model: "claude_code" or "codex")."""

    def __post_init__(self):
        super().__post_init__()
        self.proc: subprocess.Popen | None = None
        self.io = threading.Lock()  # stdin: messages, answers to permission prompts, mode switches, interrupts
        self.sent = self.answered = 0  # Claude Code: messages in and results out; stdin closes when they match
        self.closed = True
        self.cards: dict[str, dict] = {}  # tool use id → its card
        self.uses: dict[str, str] = {}  # a call's name and arguments → its id, for a prompt that doesn't name it
        self.asked: dict[str, str] = {}  # permission prompt → the card waiting on it
        self.settled: set[str] = set()  # cards a prompt declined or queued: their results don't change them
        self.plan = ""  # Claude Code's plan in Plan mode, kept for Run plan
        self.carrying_out = False  # Run plan: changes run, a command still asks
        self.held = ""  # the newest text: the answer, or a step's narration if a step follows it
        self.result: str | None = None
        self.error: str | None = None
        self.started = False
        self.cwd = Path.home()
        self.label = NAMES.get(self.model, self.model)
        self.used: list[str] = []

    # ---- the turn ------------------------------------------------------------------------------------------------
    def _run(self) -> None:
        cli = (CLIS.get(self.model) or (lambda: None))()
        if not cli:
            raise RuntimeError(f"{NAMES.get(self.model, self.model)} isn't installed on this laptop.")
        board = self.hub("GET", "board")
        if board.get("role") == "member":  # a lead's own yes is enough
            self.lead_rules = set((board.get("rules") or {}).get("lead_approves") or [])
        picked = models.current(self.model)
        self.label = NAMES[self.model] + (f" · {models.label(picked)}" if picked else "")
        self.cwd, resume = self._place()
        self.emit("start", agent={k: self.agent[k] for k in ("id", "name", "color")}, mode=self.mode, model=self.label,
                  effort=self.effort, tools=0, mcp_errors={})
        content = self.message + "".join(f"\n\n[Imported file: {a['name']}]\n{a['text'][:60_000]}" for a in self.attachments)
        answer = None
        if resume:
            try:
                answer = self._go(cli, picked, resume, self._said(content))
            except SessionGone:
                self.chat.pop("cli", None)
        if answer is None:
            answer = self._go(cli, picked, None, self._first(board, content))
        self.emit("answer", text=answer, model=self.label, usage=dict(self.spent))
        self._remember(content, answer, self.used)

    def run_plan(self) -> None:
        """Run plan: the session carries its plan out (changes run; a command still asks)."""
        self.planned, self.done = [], False
        self.carrying_out = self.looping = True
        try:
            cli, s = (CLIS.get(self.model) or (lambda: None))(), self.chat.get("cli") or {}
            if not cli or not s.get("session") or not Path(s.get("cwd") or "").is_dir():
                raise RuntimeError("that plan's session isn't on this laptop any more; ask again")
            self.cwd = Path(s["cwd"])
            answer = self._go(cli, models.current(self.model), s["session"], self._said(CARRY_OUT.format(person=self.person)))
            self.emit("text", text=answer)
            self.chat.setdefault("messages", []).extend([{"role": "user", "content": "(Run plan)"},
                                                         {"role": "assistant", "content": answer}])
            save_chat(self.chat)
        except Exception as e:  # noqa: BLE001 - shown in the chat
            self.emit("text", text=f"Couldn't carry out the plan: {e}"[:500])
        finally:
            self.carrying_out = self.looping = False
            self.done, self.ended = True, time.time()
            self.emit("end", planned=0)

    def _place(self) -> tuple[Path, str | None]:
        """Where the CLI runs and the session it continues: the chat's own session, in its folder; else a new one in the
        repo the chat worked in, the first connected repo, or a folder of Super Agents' own."""
        s = self.chat.get("cli") or {}
        if s.get("tool") == self.model and SESSION_ID.match(s.get("session") or "") and s.get("cwd") and Path(s["cwd"]).is_dir():
            return Path(s["cwd"]), s["session"]
        roots = [Path(r) for r in store.repos() if Path(r).is_dir()]
        name = chat_project(self.chat, {p.name: p.as_posix().rstrip("/").lower() for p in roots})
        cwd = next((p for p in roots if p.name == name), roots[0] if roots else None)
        if cwd is None:
            cwd = spool.home() / "workspace"
            cwd.mkdir(parents=True, exist_ok=True)
        return cwd, None

    def _first(self, board: dict, content: str) -> str:
        """A new session's first message: who it is and for whom, the team's decisions, its instructions and the chat so
        far, then the person's message."""
        members = ", ".join(m["name"] for m in board.get("members", [])) or "unknown"
        parts = [f"[Super Agents] You're {self.agent['name']}, an agent in Super Agents, the app where a software team sees "
                 f"and plans the work its developers do with AI coding agents. You work for {self.person} in the team "
                 f"\"{board.get('room', 'your team')}\" (members: {members}); {NAMES[self.model]} runs you on their "
                 f"laptop, in {self.cwd}."]
        others = [r for r in store.repos() if Path(r) != self.cwd]
        if others:
            parts.append("Other repos connected on this laptop: " + ", ".join(others) + ".")
        decisions = (board.get("rules") or {}).get("decisions") or []
        if decisions:
            parts.append("Team decisions every agent in the team follows:\n"
                         + "\n".join(f"- {d['text']} (decided by {d['by']['name']})" for d in decisions))
        if (self.agent.get("instructions") or "").strip():
            parts.append(f"Your instructions from {self.person}:\n{self.agent['instructions'].strip()}")
        earlier = self.chat.get("messages", [])[-RECAP:]
        if earlier:
            parts.append("This chat so far:\n" + "\n".join(
                f"{self.person if m['role'] == 'user' else 'You'}: {str(m.get('content') or '')[:1500]}" for m in earlier))
        return "\n\n".join(parts) + "\n\n" + self._said(content)

    def _said(self, content: str) -> str:
        """A message as the CLI gets it: how it may work this time, then what the person wrote."""
        mode = "auto" if self.carrying_out else self.mode
        return f"[{mode.capitalize()} mode: {RULES[self.model][mode].format(person=self.person)}]\n\n{content}"

    def _go(self, cli: str, picked: str | None, resume: str | None, text: str) -> str:
        return (self._claude if self.model == "claude_code" else self._codex)(cli, picked, resume, text)

    def _start(self, cmd: list[str]) -> subprocess.Popen:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}  # the app may itself run under Claude Code
        env["TEAMLOOP_AGENT"] = "superagents"  # its commits are an agent's: the commit hook links them to the task
        try:
            self.proc = subprocess.Popen(cmd, cwd=str(self.cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
        except OSError as e:
            raise RuntimeError(f"Couldn't start {NAMES[self.model]}: {e}") from None
        self.result, self.error, self.started, self.held = None, None, False, ""
        return self.proc

    @staticmethod
    def _ended(proc: subprocess.Popen, reader: threading.Thread, errors: list[str]) -> str:
        reader.join(5)
        try:
            proc.wait(30)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
        return "".join(errors).strip()

    def _keep(self, session) -> None:
        """The chat continues this CLI session next time."""
        if isinstance(session, str) and SESSION_ID.match(session):
            self.chat["cli"] = {"tool": self.model, "session": session, "cwd": str(self.cwd)}

    def _narrate(self) -> None:
        """More came after the text so far, so it wasn't the answer: it's a step's narration."""
        if self.held:
            self.emit("text", text=self.held)
            self.held = ""

    # ---- Claude Code ---------------------------------------------------------------------------------------------
    def _claude(self, cli: str, picked: str | None, resume: str | None, text: str) -> str:
        planning = self.mode == "plan" and not self.carrying_out
        cmd = [cli, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--permission-prompt-tool", "stdio", "--permission-mode", "plan" if planning else "default",
               "--effort", self.effort, *(["--resume", resume] if resume else []), *(["--model", picked] if picked else [])]
        proc = self._start(cmd)
        errors: list[str] = []
        reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
        reader.start()
        with self.io:
            self.closed, self.sent, self.answered = False, 0, 0
            self._put({"type": "control_request", "request_id": "init", "request": {"subtype": "initialize", "hooks": None}})
            self._put_message(text)
        self.emit("thinking")
        for raw in proc.stdout:
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if isinstance(d, dict):
                self._claude_line(d)
        with self.io:
            self._close()
        err = self._ended(proc, reader, errors)
        if self.cancelled:
            return self.result or self.held or "Stopped."
        if planning and self.mode == "plan" and (self.plan or STEP.search(self.result or "")):
            plan = self.plan or self.result  # its plan tool's, or a numbered plan it wrote out instead
            self.planned = ["plan"] * max(1, len(STEP.findall(plan)))
            return plan
        if self.error or self.result is None:
            why = self.error or err[-600:] or f"Claude Code exited with code {proc.returncode}"
            if resume and not self.started and GONE.search(why):
                raise SessionGone
            raise RuntimeError(why)
        return self.result or "Done."

    def _claude_line(self, d: dict) -> None:
        kind, req = d.get("type"), d.get("request") if isinstance(d.get("request"), dict) else {}
        if kind == "control_request" and req.get("subtype") == "can_use_tool":
            threading.Thread(target=self._permit, args=(str(d.get("request_id") or ""), req), daemon=True).start()
        elif kind == "control_cancel_request":  # it stopped waiting (interrupted): the card goes too
            cid = self.asked.get(str(d.get("request_id") or ""))
            if cid in self.decisions:
                self.answers[cid] = False
                self.decisions[cid].set()
        elif kind == "system" and d.get("subtype") == "init":
            self.started = True
            self._keep(d.get("session_id"))
        elif kind == "assistant" and not d.get("parent_tool_use_id"):  # a subagent's steps stay inside its card
            for b in (d.get("message") or {}).get("content") or []:
                if isinstance(b, dict):
                    self._block(b)
        elif kind == "user" and not d.get("parent_tool_use_id"):
            content = (d.get("message") or {}).get("content")
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    self._done(str(b.get("tool_use_id") or ""), _text(b.get("content")), bool(b.get("is_error")))
        elif kind == "result":
            self._claude_result(d)

    def _block(self, b: dict) -> None:
        if b.get("type") == "thinking":
            self.emit("thinking")
        elif b.get("type") == "text" and str(b.get("text") or "").strip():
            self._narrate()
            self.held = b["text"].strip()
        elif b.get("type") == "tool_use":
            name, args = str(b.get("name") or ""), b.get("input") if isinstance(b.get("input"), dict) else {}
            cid = str(b.get("id") or secrets.token_hex(4))
            new = cid not in self.cards  # (a prompt about it may have come first: then its card is already asking)
            card = self._cli_card(cid, name, args)
            self.uses[self._key(name, args)] = cid
            if new and card["name"] != "exit_plan":  # the plan shows as the answer
                self._narrate()
                self.used.append(card["name"])
                self.emit("tool", **card, status="running")

    def _done(self, cid: str, text: str, failed: bool) -> None:
        card = self.cards.get(cid)
        if card and card["name"] != "exit_plan" and cid not in self.settled:
            self.emit("tool", **card, status="failed" if failed else "done", result=text[:TO_WINDOW])
        self.emit("thinking")

    def _claude_result(self, d: dict) -> None:
        u = d.get("usage") or {}
        self.spent["calls"] += int(d.get("num_turns") or 1)
        self.spent["in"] += int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0)
        self.spent["out"] += int(u.get("output_tokens") or 0)
        self._keep(d.get("session_id"))
        if d.get("is_error"):
            self.error = str(d.get("result") or d.get("subtype") or "Claude Code stopped")[:600]
        else:
            if self.result:  # an earlier message's answer, before the note it went on to read
                self.emit("text", text=self.result)
            self.result, self.held, self.error = str(d.get("result") or self.held), "", None
        with self.io:
            self.answered += 1
            if self.answered >= self.sent:
                self._close()

    def _permit(self, rid: str, req: dict) -> None:
        name, args = str(req.get("tool_name") or ""), req.get("input") if isinstance(req.get("input"), dict) else {}
        cid = str(req.get("tool_use_id") or self.uses.get(self._key(name, args)) or f"ask-{rid}")
        card = self._cli_card(cid, name, args)
        self.asked[rid] = cid
        ok, why = self._gate(card)
        self.asked.pop(rid, None)
        reply = {"behavior": "allow", "updatedInput": args} if ok else {"behavior": "deny", "message": why}
        self._write({"type": "control_response", "response": {"subtype": "success", "request_id": rid, "response": reply}})

    def _gate(self, card: dict) -> tuple[bool, str]:
        """A step Claude Code asks to take, decided as the app decides its own tools' steps."""
        cid, kind, name = card["id"], card["access"], card["name"]
        if name == "exit_plan":  # its plan is ready: in Plan the person reviews it here, else it carries on
            if self.mode == "plan" and not self.carrying_out:
                self.plan = str(card["args"].get("plan") or "")
                return False, PLAN_KEPT
            return True, ""
        if kind == "read":
            return True, ""
        if self.mode == "plan" and not self.carrying_out:
            return self._planned(card)
        if LEAD_RULE.get(name) in self.lead_rules:
            ok, why = self._ask_lead(cid, card, name, card["args"])
            if not ok:
                self.settled.add(cid)
                self.emit("tool", **card, status="declined", result=why)
                return False, f"{why} Don't retry it; tell the person."
        elif kind == "ask" or (kind == "change" and self.mode == "manual" and not self.carrying_out):
            ev = self.decisions[cid] = threading.Event()
            self.waiting[cid] = kind
            self.emit("tool", **card, status="asking")
            ev.wait()
            self.waiting.pop(cid, None)
            if self.cancelled or not self.answers.get(cid):
                self.settled.add(cid)
                self.emit("tool", **card, status="declined")
                return False, "The person declined this. Don't retry it; ask them, or go on without it."
            if self.mode == "plan" and not self.carrying_out:  # switched to Plan while it waited
                return self._planned(card)
        self.emit("tool", **card, status="running")
        return True, ""

    def _planned(self, card: dict) -> tuple[bool, str]:
        self.settled.add(card["id"])
        self.emit("tool", **card, status="planned")
        return False, "Not run: plan mode. Leave it for the plan; the person reviews the plan and runs it."

    def _cli_card(self, cid: str, name: str, args: dict) -> dict:
        if cid not in self.cards:
            card, kind, shown, group = card_of(name, args)
            self.cards[cid] = {"id": cid, "name": card, "args": shown, "access": kind, "group": group}
        return self.cards[cid]

    @staticmethod
    def _key(name: str, args: dict) -> str:
        return f"{name}:{json.dumps(args, sort_keys=True)}"

    def _write(self, d: dict) -> bool:
        with self.io:
            return self._put(d)

    def _put(self, d: dict) -> bool:  # with self.io held
        if self.closed or not self.proc:
            return False
        try:
            self.proc.stdin.write(json.dumps(d) + "\n")
            self.proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def _put_message(self, text: str) -> None:  # with self.io held
        if self._put({"type": "user", "message": {"role": "user", "content": text}, "parent_tool_use_id": None,
                      "session_id": "default"}):
            self.sent += 1

    def _close(self) -> None:  # with self.io held: no more messages, so it ends once it has answered
        if not self.closed:
            self.closed = True
            try:
                self.proc.stdin.close()
            except (OSError, AttributeError):
                pass

    # ---- Codex ---------------------------------------------------------------------------------------------------
    def _codex(self, cli: str, picked: str | None, resume: str | None, text: str) -> str:
        while True:
            sandbox = "workspace-write" if self.mode == "auto" or self.carrying_out else "read-only"
            fd, out = tempfile.mkstemp(prefix="superagents-", suffix=".txt")
            os.close(fd)
            cmd = ([cli, "exec", "resume", resume, "-", "--json", "-o", out, "-c", f"sandbox_mode={sandbox}"] if resume
                   else [cli, "exec", "-", "--json", "-o", out, "-s", sandbox])
            cmd += ["--skip-git-repo-check", *(["-m", picked] if picked else []),
                    "-c", f"model_reasoning_effort={CODEX_EFFORT[self.effort]}"]
            proc = self._start(cmd)
            errors: list[str] = []
            reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
            reader.start()
            try:
                proc.stdin.write(text)
                proc.stdin.close()
            except OSError:  # it exited before reading the message; stderr says why
                pass
            self.emit("thinking")
            for raw in proc.stdout:
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    self._codex_line(d)
            err = self._ended(proc, reader, errors)
            try:
                answer = Path(out).read_text(encoding="utf-8").strip() or self.held
            except OSError:
                answer = self.held
            Path(out).unlink(missing_ok=True)
            if self.cancelled:
                return answer or "Stopped."
            if not answer:
                why = self.error or err[-600:] or f"Codex exited with code {proc.returncode}"
                if resume and not self.started and GONE.search(why):
                    raise SessionGone
                raise RuntimeError(why)
            resume = (self.chat.get("cli") or {}).get("session") or resume
            with self.cond:
                notes, self.steers = self.steers, []
            if not notes or not resume:
                break
            self.emit("text", text=answer)  # its answer so far; then the notes typed while it worked
            text = "\n\n".join(STEER.format(who=self.person + (" (from their phone)" if via == "phone" else ""), text=t)
                               for t, via in notes)
        if self.mode == "plan" and not self.carrying_out:
            self.planned = ["plan"] * len(STEP.findall(answer))
        return answer

    def _codex_line(self, d: dict) -> None:
        kind, item = d.get("type") or "", d.get("item") if isinstance(d.get("item"), dict) else {}
        if kind == "thread.started":
            self.started = True
            self._keep(d.get("thread_id"))
        elif kind in ("item.started", "item.completed"):
            mapped = codex_card(item)
            if item.get("type") == "agent_message" and kind == "item.completed" and str(item.get("text") or "").strip():
                self._narrate()
                self.held = item["text"].strip()
            elif item.get("type") == "reasoning":
                self.emit("thinking")
            elif mapped:
                cid = str(item.get("id") or secrets.token_hex(4))
                if cid not in self.cards:
                    card, access, shown, group = mapped
                    self.cards[cid] = {"id": cid, "name": card, "args": shown, "access": access, "group": group}
                    self._narrate()
                    self.used.append(card)
                if kind == "item.started":
                    self.emit("tool", **self.cards[cid], status="running")
                else:
                    err = item.get("error") if isinstance(item.get("error"), dict) else {}
                    failed = item.get("status") == "failed" or item.get("exit_code") not in (None, 0)
                    self.emit("tool", **self.cards[cid], status="failed" if failed else "done",
                              result=str(item.get("aggregated_output") or err.get("message") or "")[:TO_WINDOW])
                    self.emit("thinking")
        elif kind == "turn.completed":
            u = d.get("usage") or {}
            self.spent["calls"] += 1
            self.spent["in"] += max(0, int(u.get("input_tokens") or 0) - int(u.get("cached_input_tokens") or 0))
            self.spent["out"] += int(u.get("output_tokens") or 0)
        elif kind in ("turn.failed", "error"):
            err = d.get("error") if isinstance(d.get("error"), dict) else d
            self.error = str(err.get("message") or "Codex stopped")[:600]

    # ---- while it works -------------------------------------------------------------------------------------------
    def steer(self, text: str, via: str = "desk") -> bool:
        """A note typed while it works: Claude Code reads it as its next message; Codex when the run in progress ends."""
        if self.model != "claude_code":
            return super().steer(text, via)
        who = self.person + (" (from their phone)" if via == "phone" else "")
        with self.io:
            if self.closed:
                return False
            self._put_message(STEER.format(who=who, text=text))
        self.emit("steer", text=text, via=via)
        return True

    def set_mode(self, mode: str) -> None:
        """As for a Nemotron turn; Claude Code also moves between its plan mode and its default one."""
        was = self.mode
        super().set_mode(mode)
        if self.model == "claude_code" and self.mode != was and "plan" in (was, self.mode):
            self._write({"type": "control_request", "request_id": f"mode-{secrets.token_hex(3)}",
                         "request": {"subtype": "set_permission_mode", "mode": "plan" if self.mode == "plan" else "default"}})

    def cancel(self) -> None:
        super().cancel()
        proc = self.proc
        if proc and proc.poll() is None:
            if self.model == "claude_code" and self._write({"type": "control_request", "request_id": "stop",
                                                             "request": {"subtype": "interrupt"}}):
                threading.Timer(5, _kill_tree, args=(proc,)).start()  # in case it doesn't stop by itself
            else:
                _kill_tree(proc)
