"""Hook payload -> one `teamloop.event/v1` record (PLAN.md §8).

Field maps come from real payloads in tests/fixtures/hooks/<tool>/. Two facts from those captures shape this file:
- Claude Code's PostToolUse for Bash carries no exit code. A non-zero exit arrives as PostToolUseFailure with
  error "Exit code N\\n<output>".
- Free text (the agent's last message) goes in `local`, which never leaves the laptop. `facts` hold only
  structured values: tool names, repo-relative paths, test counts, exit codes.
"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_KINDS = [  # first match wins
    ("test", re.compile(r"\b(py\.?test|unittest|jest|vitest|mocha|rspec|phpunit|go test|cargo test|dotnet test|mvn test|"
                        r"gradle test|(npm|pnpm|yarn|bun)( run)? test)\b")),
    ("git", re.compile(r"(^|[;&|]\s*)git\s+(commit|push|merge|rebase|checkout|switch|pull|cherry-pick)\b")),
    ("install", re.compile(r"\b(pip install|uv (pip install|add|sync)|(npm|pnpm|bun) (i|install|ci|add)|yarn add|"
                           r"cargo add|go get)\b")),
    ("build", re.compile(r"\b((npm|pnpm|yarn|bun)( run)? build|vite build|tsc|cargo build|go build|make|gradle build|"
                         r"mvn package|dotnet build|docker build)\b")),
]
_COUNTS = re.compile(r"\b(\d+) (passed|failed|errors?)\b")
_EXIT = re.compile(r"^Exit code (\d+)")
_WIN_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def event(kind: str, tool: str, payload: dict, facts: dict | None = None, local: dict | None = None) -> dict:
    return {
        "v": 1,
        "id": uuid.uuid4().hex,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": tool,
        "session": payload.get("session_id"),
        "kind": kind,
        "facts": facts or {},
        "local": local or {},
    }


def rel(path: str, root: Path | None) -> str:
    """Repo-relative POSIX path; outside the repo, only the file name (never a machine path).
    The payload's own path style decides the flavour, so Windows fixtures also pass on Linux CI."""
    flavour = PureWindowsPath if _WIN_PATH.match(path) else PurePosixPath
    p = flavour(path)
    if root is not None:
        try:
            return p.relative_to(flavour(str(root))).as_posix()
        except ValueError:
            pass
    return p.name


def command_kind(cmd: str) -> str:
    for kind, pattern in _KINDS:
        if pattern.search(cmd):
            return kind
    return "other"


def count_tests(output: str) -> dict:
    """Totals from the last test summary line in the output, e.g. "1 failed, 2 passed in 0.3s"."""
    counts: dict[str, int] = {}
    for line in output.splitlines():
        found = _COUNTS.findall(line)
        if found:
            counts = {}
            for n, word in found:
                key = "passed" if word == "passed" else "failed"
                counts[key] = counts.get(key, 0) + int(n)
    return counts


def claude_code(p: dict, root: Path | None) -> dict | None:
    name, tool = p.get("hook_event_name"), "claude_code"
    if name == "SessionStart":
        return event("session_start", tool, p, {"source": p.get("source")})
    if name in ("PostToolUse", "PostToolUseFailure"):
        ok = name == "PostToolUse"
        used, args = p.get("tool_name") or "", p.get("tool_input") or {}
        facts: dict[str, Any] = {"tool": used, "ok": ok, "ms": p.get("duration_ms")}
        if used in EDIT_TOOLS and args.get("file_path"):
            facts["file"] = rel(args["file_path"], root)
        if not ok:
            m = _EXIT.match(p.get("error") or "")
            if m:
                facts["exit"] = int(m.group(1))
        if used == "Bash":
            out = ((p.get("tool_response") or {}).get("stdout") or "") if ok else (p.get("error") or "")
            cmd = {"kind": command_kind(args.get("command") or ""), "ok": ok}
            if cmd["kind"] == "test":
                cmd.update(count_tests(out))
                if cmd.get("failed"):
                    cmd["ok"] = False
            facts["cmd"] = cmd
        return event("tool", tool, p, facts)
    if name in ("Stop", "SubagentStop"):
        kind = "turn_end" if name == "Stop" else "subagent_end"
        return event(kind, tool, p, local={"text": p.get("last_assistant_message") or ""})
    if name == "Notification":
        return event("waiting_input", tool, p, {"type": p.get("notification_type")})
    if name == "SessionEnd":
        return event("session_end", tool, p, {"reason": p.get("reason")})
    return None


NORMALIZERS: dict[str, Callable[[dict, Path | None], dict | None]] = {"claude_code": claude_code}
