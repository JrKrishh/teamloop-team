"""Super Team on this laptop: teammates' prompts into your coding sessions, run by your rules.

The hub keeps the prompts and your rules: off, ask each time, or automatic; read only or edit; tokens per teammate
per day. This polls for prompts you (or your rules) approved, runs each against the session it names with that tool's
own CLI, in that session's repo, and reports the answer and the tokens used. Your open session isn't touched: Claude
Code runs a fork of it (--fork-session); Codex continues it in the background.

Claude Code runs in its --restricted mode: no command or code tools, file tools confined to the repo, your own
allow-rules don't apply, and no MCP servers load. Read-only runs also deny edits; edit runs accept edits. Codex runs in
its read-only or workspace-write sandbox. A run stops at the teammate's token budget for the day (checked as each
message arrives, so the message that crosses it still finishes) or after ten minutes.

The prompt goes in on stdin, never on the command line: argv holds only fixed flags and a checked session id, so a
Windows command shim (claude.cmd, codex.cmd) has nothing to misread.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from teamloop import claude, codex, spool

POLL_SECONDS = 15
TIMEOUT = 600
RESULT_MAX = 12_000
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{4,80}$")
TOOL_NAMES = {"claude_code": "Claude Code", "codex": "Codex"}


def framed(p: dict) -> str:
    """The teammate's prompt, with who sent it and what this run may do."""
    who, owner = p["from"]["name"], p["to"]["name"]
    rights = ("You may read files in this repo but not change anything." if p["access"] == "read"
              else "You may read and edit files in this repo; you can't run commands.")
    return (f"[Super Team] {who} is asking, through Super Agents, with {owner}'s permission. {rights} "
            f"Answer {who} directly.\n\n{p['prompt']}")


def command(p: dict, cli: str, last_message: Optional[str] = None) -> list[str]:
    if not SESSION_ID.match(p["session"] or ""):
        raise ValueError("That session id doesn't look right")
    if p["tool"] == "claude_code":
        cmd = [cli, "-p", "--resume", p["session"], "--fork-session", "--output-format", "stream-json", "--verbose",
               "--restricted", "--strict-mcp-config"]  # and none of the owner's MCP servers
        if p["access"] == "read":
            return cmd + ["--permission-mode", "dontAsk", "--disallowedTools", "Edit,Write,MultiEdit,NotebookEdit"]
        return cmd + ["--permission-mode", "acceptEdits"]
    if p["tool"] == "codex":
        sandbox = "read-only" if p["access"] == "read" else "workspace-write"
        return [cli, "exec", "resume", p["session"], "-", "--json", "-o", last_message or os.devnull,
                "-c", f"sandbox_mode={sandbox}", "--skip-git-repo-check"]
    raise ValueError(f"{p['tool']} sessions can't take prompts")


@dataclass
class Run:
    """What a run produced, read from the CLI's JSON lines as they arrive."""
    budget: Optional[int]
    tokens: int = 0
    text: list = field(default_factory=list)
    result: Optional[str] = None
    error: Optional[str] = None
    session: Optional[str] = None
    over: bool = False
    seen: set = field(default_factory=set)

    def line(self, tool: str, raw: str) -> None:
        try:
            d = json.loads(raw)
        except ValueError:
            return
        if not isinstance(d, dict):
            return
        if tool == "claude_code":
            self._claude(d)
        else:
            self._codex(d)
        if self.budget is not None and self.tokens > self.budget:
            self.over = True

    def _claude(self, d: dict) -> None:
        kind = d.get("type")
        if kind == "system" and d.get("session_id"):
            self.session = d["session_id"]
        elif kind == "assistant":
            msg = d.get("message") or {}
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                    self.text.append(block["text"])
            if msg.get("id") not in self.seen:  # usage repeats on each content block of a request
                self.seen.add(msg.get("id"))
                u = msg.get("usage") or {}
                self.tokens += sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "output_tokens"))
        elif kind == "result":
            self.session = d.get("session_id") or self.session
            u = d.get("usage") or {}
            final = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "output_tokens"))
            self.tokens = max(self.tokens, final)
            if d.get("is_error"):
                self.error = str(d.get("result") or d.get("subtype") or "the run failed")
            else:
                self.result = str(d.get("result") or "")

    def _codex(self, d: dict) -> None:
        kind = d.get("type") or ""
        if kind == "thread.started":
            self.session = d.get("thread_id") or self.session
        elif kind == "item.completed":
            item = d.get("item") or {}
            if item.get("type") in ("agent_message", "assistant_message") and item.get("text"):
                self.text.append(item["text"])
        elif kind == "turn.completed":
            u = d.get("usage") or {}
            fresh = max(0, int(u.get("input_tokens") or 0) - int(u.get("cached_input_tokens") or 0))
            self.tokens += fresh + int(u.get("output_tokens") or 0)
        elif kind in ("turn.failed", "error"):
            err = d.get("error") or d
            self.error = str(err.get("message") if isinstance(err, dict) else err)[:500]

    def answer(self) -> str:
        return (self.result if self.result is not None else "\n\n".join(self.text)).strip()


def _minutes(seconds: float) -> str:
    n = max(1, round(seconds / 60))
    return f"{n} minute{'s' if n != 1 else ''}"


def _kill_tree(proc: subprocess.Popen) -> None:
    """A command shim's child (node) outlives killing the shim alone; take the whole tree."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()


def run(p: dict, repo: Path, cli: str, budget: Optional[int], timeout: float = TIMEOUT) -> dict:
    """Run one prompt; return what /v1/prompts/{id}/finish takes."""
    out_file = None
    if p["tool"] == "codex":
        fd, out_file = tempfile.mkstemp(prefix="superteam-", suffix=".txt")
        os.close(fd)
    state = Run(budget)
    try:
        proc = subprocess.Popen(command(p, cli, out_file), cwd=str(repo), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        return {"status": "failed", "result": f"Couldn't start {TOOL_NAMES[p['tool']]}: {e}", "tokens": 0}
    late = threading.Event()

    def too_long() -> None:
        late.set()
        _kill_tree(proc)

    timer = threading.Timer(timeout, too_long)
    timer.start()
    errors: list[str] = []
    reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    reader.start()
    try:
        try:
            proc.stdin.write(framed(p))
            proc.stdin.close()
        except OSError:  # it exited before reading the prompt; stderr says why
            pass
        for line in proc.stdout:
            state.line(p["tool"], line)
            if state.over:
                _kill_tree(proc)
                break
        proc.wait(30)
        reader.join(5)
    finally:
        timer.cancel()
    if out_file:
        try:
            last = Path(out_file).read_text(encoding="utf-8").strip()
            state.result = last or state.result
        except OSError:
            pass
        Path(out_file).unlink(missing_ok=True)
    answer = state.answer()
    if state.over:
        return {"status": "stopped", "tokens": state.tokens, "run_session": state.session,
                "result": (answer + "\n\n" if answer else "")
                + f"(Stopped: {p['from']['name']}'s tokens for today ran out; {budget:,} {'was' if budget == 1 else 'were'} "
                  "left when it started.)"}
    if late.is_set():
        return {"status": "stopped", "tokens": state.tokens, "run_session": state.session,
                "result": (answer + "\n\n" if answer else "") + f"(Stopped after {_minutes(timeout)}.)"}
    if state.error or proc.returncode not in (0, None) or not answer:
        why = state.error or ("".join(errors).strip()[-600:]) or f"{TOOL_NAMES[p['tool']]} exited with code {proc.returncode}"
        return {"status": "failed", "result": why, "tokens": state.tokens, "run_session": state.session}
    return {"status": "done", "result": answer, "tokens": state.tokens, "run_session": state.session}


class Runner:
    """Polls the hub for this person's approved prompts and runs them one at a time."""

    def __init__(self, call: Callable, team: Callable[[], Optional[str]], repos: Callable[[], list[dict]],
                 clis: Optional[dict] = None, poll: float = POLL_SECONDS):
        self.call = call            # call(method, path, body, query) -> (status, json), with this person's session
        self.team = team
        self.repos = repos
        self.clis = clis or {"claude_code": claude.cli, "codex": codex.cli}
        self.poll = poll
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.current: Optional[dict] = None

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="super-team").start()

    def poke(self) -> None:
        """Look now (you just allowed a prompt) instead of at the next poll."""
        self.wake.set()

    def _loop(self) -> None:
        while not self.stop.is_set():
            self.wake.wait(self.poll)
            self.wake.clear()
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001 - logged; the next poll tries again
                _log()

    def poll_once(self) -> int:
        team = self.team()
        if not team:
            return 0
        code, data = self.call("GET", "/v1/prompts/runnable", None, {"team": team})
        if code != 200:
            return 0
        done = 0
        for p in data.get("prompts", []):
            code, claimed = self.call("POST", f"/v1/prompts/{p['id']}/claim", {}, {"team": team})
            if code != 200:
                continue
            self.current = claimed
            try:
                out = self.run_one(claimed)
            finally:
                self.current = None
            out["result"] = (out.get("result") or "")[:RESULT_MAX]
            self.call("POST", f"/v1/prompts/{p['id']}/finish", out, {"team": team})
            done += 1
        return done

    def run_one(self, p: dict) -> dict:
        repo = next((Path(r["path"]) for r in self.repos() if r.get("ok") and r.get("name") == p.get("repo")), None)
        if repo is None:
            return {"status": "failed", "tokens": 0,
                    "result": f"The repo of this session ({p.get('repo') or 'unknown'}) isn't connected in {p['to']['name']}'s "
                              "Super Agents (This laptop → Connect a repo)."}
        cli = (self.clis.get(p["tool"]) or (lambda: None))()
        if not cli:
            return {"status": "failed", "tokens": 0, "result": f"{TOOL_NAMES.get(p['tool'], p['tool'])} isn't installed here."}
        try:
            return run(p, repo, cli, p.get("budget"))
        except ValueError as e:
            return {"status": "failed", "tokens": 0, "result": str(e)}


def _log() -> None:
    try:
        path = spool.home() / "superteam.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{traceback.format_exc()}\n")
    except OSError:
        pass
