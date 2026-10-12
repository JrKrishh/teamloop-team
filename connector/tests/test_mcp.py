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
    assert names == ["mark_blocked", "report_progress", "task_start"]
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
