"""Agents: each has its own name, hood colour, instructions, default model and mode, skills, MCP connectors and
built-in tool groups. Agent S is built in (its instructions are editable, it can't be deleted); you can add more,
like a reviewer or a release manager. Kept in ~/.teamloop/agents.json."""

from __future__ import annotations

import json
import re
import secrets

from teamloop import spool

from . import skills

TOOL_GROUPS = ("team", "files", "terminal", "browser", "memory", "desktop")
OFF_UNTIL_ON = {"desktop"}  # using the person's own apps is something they turn on, per agent
COLOURS = ("#C2554C", "#3E9B6B", "#8E6BD8", "#D98A2B", "#7A8B3A", "#3E7CB1", "#C44D8E")
DEFAULT = {"id": "agent-s", "name": "Agent S", "color": "#C2554C", "builtin": True,
           "instructions": "", "model": "auto", "mode": "manual", "skills": [*skills.DEFAULT_ON, "code-review"], "connectors": [],
           "tools": {g: g not in OFF_UNTIL_ON for g in TOOL_GROUPS}}
ID = re.compile(r"^[a-z0-9-]{3,40}$")


def _path():
    return spool.home() / "agents.json"


def all_agents() -> list[dict]:
    try:
        saved = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = []
    by_id = {a["id"]: a for a in saved if isinstance(a, dict) and ID.match(str(a.get("id", "")))}
    agent_s = {**DEFAULT, **{k: v for k, v in by_id.pop("agent-s", {}).items() if k not in ("id", "builtin")}}
    return [agent_s] + [{**DEFAULT, **a, "builtin": False} for a in by_id.values()]


def get(agent_id: str) -> dict:
    return next((a for a in all_agents() if a["id"] == agent_id), all_agents()[0])


def _write(agents: list[dict]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{k: v for k, v in a.items() if k != "builtin"} for a in agents], indent=2), encoding="utf-8")


def clean(fields: dict) -> dict:
    out = {}
    if "name" in fields:
        out["name"] = " ".join(str(fields["name"]).split())[:40] or "Agent"
    if "color" in fields and str(fields["color"]) in COLOURS:
        out["color"] = fields["color"]
    if "instructions" in fields:
        out["instructions"] = str(fields["instructions"])[:8000]
    if fields.get("model") in ("auto", "lightning", "super", "ultra", "claude_code", "codex"):
        out["model"] = fields["model"]
    if fields.get("mode") in ("manual", "auto", "plan"):
        out["mode"] = fields["mode"]
    if isinstance(fields.get("skills"), list):
        out["skills"] = [s for s in fields["skills"] if isinstance(s, str) and skills.NAME.match(s)][:30]
    if isinstance(fields.get("connectors"), list):
        out["connectors"] = [c for c in fields["connectors"] if isinstance(c, str)][:20]
    if isinstance(fields.get("tools"), dict):
        out["tools"] = {g: bool(fields["tools"].get(g, g not in OFF_UNTIL_ON)) for g in TOOL_GROUPS}
    return out


def save(agent_id: str | None, fields: dict) -> dict:
    agents = all_agents()
    if agent_id:
        agent = next((a for a in agents if a["id"] == agent_id), None)
        if not agent:
            raise KeyError(agent_id)
        agent.update(clean(fields))
    else:
        agent = {**DEFAULT, "id": "agent-" + secrets.token_hex(3), "builtin": False, "name": "New agent",
                 "color": COLOURS[len(agents) % len(COLOURS)], **clean(fields)}
        agents.append(agent)
    _write(agents)
    return agent


def delete(agent_id: str) -> None:
    if agent_id == "agent-s":
        raise PermissionError("Agent S is built in")
    agents = [a for a in all_agents() if a["id"] != agent_id]
    _write(agents)
