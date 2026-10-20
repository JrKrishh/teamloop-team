"""Which model a person's Claude Code or Codex session runs on, read from that tool's own files on this laptop.

- Claude Code writes the model the person picked (requestedModel, e.g. claude-opus-5-5[1m]) and the one that answered
  (message.model) on each assistant line of the session's transcript.
- Codex writes each turn's model in a turn_context line of the session's rollout (sessions/YYYY/MM/DD/rollout-*-<id>).
- With no session to read, the tool's own default answers: Claude Code's settings.json, Codex's config.toml.

Only a model's name comes out of here, and only one that's safe on a command line.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path

TAIL = 1_000_000
SESSION = re.compile(r"^[A-Za-z0-9_-]{4,80}$")
# a model's name as it may go on a command line: claude-opus-5-5, claude-opus-5-5[1m], opus, gpt-6-astra
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}(\[[0-9a-z]{1,8}\])?$")


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _ok(model) -> str | None:
    return model if isinstance(model, str) and MODEL_ID.match(model) else None


def _tail(path: Path) -> list[bytes]:
    size = path.stat().st_size
    with open(path, "rb") as f:
        f.seek(max(0, size - TAIL))
        lines = f.read().splitlines()
    return lines[1:] if size > TAIL else lines  # began mid-line


def _claude_model(path: Path) -> str | None:
    for raw in reversed(_tail(path)):
        if b'"assistant"' not in raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        msg = d.get("message") if isinstance(d.get("message"), dict) else {}
        model = _ok(d.get("requestedModel")) or (_ok(msg.get("model")) if msg.get("model") != "<synthetic>" else None)
        if model:
            return model
    return None


def _codex_model(path: Path) -> str | None:
    for raw in reversed(_tail(path)):
        if b'"turn_context"' not in raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if d.get("type") == "turn_context" and isinstance(d.get("payload"), dict) and _ok(d["payload"].get("model")):
            return d["payload"]["model"]
    return None


def _read(tool: str, path: Path | None) -> str | None:
    try:
        return (_claude_model if tool == "claude_code" else _codex_model)(path) if path else None
    except OSError:
        return None


def _newest(files) -> Path | None:
    best, at = None, 0.0
    for f in files:
        try:
            m = f.stat().st_mtime
        except OSError:
            continue
        if m > at:
            best, at = f, m
    return best


def of_session(tool: str, session: str) -> str | None:
    """The model that session runs on now; None when its file isn't on this laptop."""
    if not SESSION.match(session or ""):
        return None
    if tool == "claude_code":
        files = (claude_home() / "projects").glob(f"*/{session}.jsonl")
    elif tool == "codex":
        files = (codex_home() / "sessions").glob(f"*/*/*/rollout-*-{session}.jsonl")
    else:
        return None
    return _read(tool, _newest(files))


def default(tool: str) -> str | None:
    """The tool's own default model, when the person set one."""
    try:
        if tool == "claude_code":
            return _ok(json.loads((claude_home() / "settings.json").read_text(encoding="utf-8")).get("model"))
        if tool == "codex":
            return _ok(tomllib.loads((codex_home() / "config.toml").read_text(encoding="utf-8")).get("model"))
    except (OSError, ValueError, AttributeError):  # missing, unreadable, or not the shape we know
        return None
    return None


def current(tool: str) -> str | None:
    """The model the person picked in that tool lately: their newest session's, else the tool's default. None leaves the
    choice to the tool."""
    if tool == "claude_code":
        path = _newest((claude_home() / "projects").glob("*/*.jsonl"))
    elif tool == "codex":
        days = sorted((codex_home() / "sessions").glob("*/*/*"), reverse=True)[:7]  # YYYY/MM/DD: the newest days
        path = _newest(f for d in days for f in d.glob("rollout-*.jsonl"))
    else:
        return None
    return _read(tool, path) or default(tool)


def label(model: str | None) -> str:
    """A model's name as people say it: claude-opus-5-5[1m] → Opus 5.5 (1M); other tools' names stay as they are."""
    if not model:
        return ""
    core = model.removeprefix("claude-")
    if core == model and core not in ("opus", "sonnet", "haiku", "fable"):
        return model
    wide = " (1M)" if core.endswith("[1m]") else ""
    parts = re.sub(r"-\d{8}$", "", re.sub(r"\[.*\]$", "", core)).split("-")
    words, nums = [p for p in parts if p.isalpha()], [p for p in parts if p.isdigit()]
    return f"{words[0].capitalize()} {'.'.join(nums)}".strip() + wide if words else model
