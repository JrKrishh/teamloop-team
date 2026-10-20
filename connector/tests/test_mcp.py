"""The MCP server over real stdio, the way Claude Code / Codex / Cursor run it."""

import asyncio
import json
import os
import subprocess
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from teamloop import spool

CANARY = "ghp_" + "Q" * 36


def call_tools(cwd, home, calls):
    params = StdioServerParameters(command=sys.executable, args=["-m", "teamloop", "mcp"], cwd=str(cwd),
                                   env={**os.environ, "TEAMLOOP_HOME": str(home)})

    async def go(errlog):
        async with stdio_client(params, errlog=errlog) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = sorted(t.name for t in (await s.list_tools()).tools)
            out = [(await s.call_tool(name, args)).content[0].text for name, args in calls]
            return names, out

    # pytest's captured stderr has no real file handle, which stalls the Windows subprocess transport
    with open(home.parent / "mcp-stderr.log", "w") as errlog:
        return asyncio.run(go(errlog))


def test_tools_record_self_reports(tmp_path, teamloop_home):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    names, out = call_tools(tmp_path, teamloop_home, [
        ("task_start", {"task_id": "T-4", "title": "Board skeleton"}),
        ("report_progress", {"percent": 140, "done": ["lanes render", "x" * 400], "doing": f"wiring SSE with {CANARY}",
                             "next_steps": ["cards", "", "timeline"]}),
        ("mark_blocked", {"reason": "need the hub URL", "needs": "info"}),
        ("task_start", {"task_id": "not an id"}),
    ])
    assert names == ["ask_status", "ask_teammate", "get_team_status", "handoff", "mark_blocked", "message_teammate",
                     "read_messages", "report_progress", "task_start", "team_changes"]
    assert out[0] == "Tracking T-4." and "100%" in out[1] and "blocked" in out[2] and "not a task ID" in out[3]
    assert subprocess.run(["git", "config", "teamloop.task"], cwd=tmp_path, capture_output=True, text=True).stdout.strip() == "T-4"

    events = [spool.read(p) for p in spool.pending()]
    assert [e["kind"] for e in events] == ["task_start", "self_report", "blocked"]
    report = events[1]["report"]
    assert report["percent"] == 100 and report["next"] == ["cards", "timeline"]
    assert len(report["done"][1]) == 160 and CANARY not in json.dumps(events)
    assert all(e["task"] == "T-4" and e["tool"] == "mcp" for e in events)
    assert events[2]["report"] == {"reason": "need the hub URL", "needs": "info"}
    assert "report" in spool.public(events[1])  # self-reports are written for the team on purpose


def test_mcp_server_hosts_the_sender(tmp_path, teamloop_home):
    """No extra process: while the coding session's MCP server runs, the spool drains to the hub."""
    from test_send import Hub

    hub = Hub()
    teamloop_home.mkdir(parents=True, exist_ok=True)
    (teamloop_home / "config.json").write_text(json.dumps(
        {"url": hub.url, "room": "team-room", "token": "t", "name": "yang", "identity_key": "k" * 32}))
    subprocess.run(["git", "init", "-q", "-b", "T-12-x"], cwd=tmp_path, check=True)
    calls = [("report_progress", {"percent": 50, "done": ["a"], "doing": "b", "next_steps": ["c"]})]
    params = StdioServerParameters(command=sys.executable, args=["-m", "teamloop", "mcp"], cwd=str(tmp_path),
                                   env={**os.environ, "TEAMLOOP_HOME": str(teamloop_home), "TEAMLOOP_SUMMARIZER": "off"})

    async def go(errlog):
        async with stdio_client(params, errlog=errlog) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await s.call_tool(*calls[0])
            for _ in range(60):  # the sender thread polls every 5 s
                if hub.bodies:
                    break
                await asyncio.sleep(0.25)

    with open(teamloop_home.parent / "mcp-stderr.log", "w") as errlog:
        asyncio.run(go(errlog))
    hub.server.shutdown()
    events = json.loads(hub.bodies[0])["events"]
    assert events[0]["kind"] == "self_report" and events[0]["task"] == "T-12" and events[0]["member"] == "yang"
    assert spool.pending() == []


def test_team_status_without_a_hub(teamloop_home):
    from teamloop import mcp_server

    assert "teamloop login" in mcp_server.get_team_status()


def test_team_status_text_is_framed_and_compact():
    from teamloop import mcp_server

    board = {"room": "teamloop", "members": [{"name": "yang", "active": True}, {"name": "asha", "active": False}],
             "tasks": [{"task": "T-22", "title": "Snapshots migration", "status": "blocked", "members": ["sourabh"], "pr": None,
                        "progress": {"percent": 40, "agent_says_percent": None,
                                     "blockers": [{"text": "DB user is read-only", "evidence_ids": ["x"]}], "doing": [], "next": []}}]}
    text = mcp_server.team_status_text(board)
    assert text.startswith(mcp_server.FRAME) and "Active now: yang" in text
    assert "- T-22 Snapshots migration: blocked, Agent S 40%; sourabh" in text and "blockers: DB user is read-only" in text
    who = [{"member": "asha", "tool": "cursor", "task": "T-19"}, {"member": "yang", "tool": "codex", "task": None}]
    board.update(overlaps=[{"repo": "acme-web", "file": "src/auth.py", "who": who}],
                 touching=[{"repo": "acme-web", "file": "src/auth.py", "who": who}])
    text = mcp_server.team_status_text(board)
    assert "Overlap: acme-web/src/auth.py was edited by more than one session in the last half hour: asha (Cursor, T-19), yang (Codex)." in text
    assert "Being edited now: acme-web/src/auth.py (asha)" in text
