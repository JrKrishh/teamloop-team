"""Build the public demo room's data: hub/hub/demo/demo.json.

The events are scripted. They are a sample team building TeamLoop itself, in the exact shapes the connector,
MCP tools and GitHub receiver emit. The progress snapshots are NOT hand-written: this script runs the real
Agent S over each task, and the snapshot records which model produced it. Re-run once Nemotron credits are live:

    AGENT_S_PROVIDER=nebius python scripts/build_demo.py
"""

import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_s"))
from agent_s import progress  # noqa: E402

events: list[dict] = []


def ev(minutes_ago, member, task, branch, tool, kind, facts=None, **extra):
    """minutes_ago is relative to the moment the hub seeds the demo, so the board always looks live."""
    e = {"v": 1, "id": uuid.uuid4().hex, "offset_min": minutes_ago, "tool": tool, "session": f"{member}-{task}",
         "kind": kind, "facts": facts or {}, "member": member, "repo": "teamloop-team", "branch": branch, "task": task}
    e.update(extra)
    events.append(e)


def test(ok, passed=0, failed=0):
    cmd = {"kind": "test", "ok": ok}
    if passed:
        cmd["passed"] = passed
    if failed:
        cmd["failed"] = failed
    return {"tool": "Bash", "ok": True, "cmd": cmd}


# T-21: yang, Claude Code, SSE stream for the board. Mid-way, honest 60% self-report.
b = "T-21-board-sse"
ev(95, "yang", "T-21", b, "claude_code", "session_start", {"source": "startup"})
ev(94, "yang", "T-21", None, "mcp", "task_start", {"title": "SSE stream for the board"})
ev(90, "yang", "T-21", b, "claude_code", "tool", {"tool": "Write", "ok": True, "file": "hub/hub/stream.py"})
ev(84, "yang", "T-21", b, "claude_code", "tool", test(False, passed=3, failed=2))
ev(83, "yang", "T-21", b, "claude_code", "turn_end", summary="Added a first /v1/stream endpoint; 2 of 5 stream tests fail on reconnect.", status="progress")
ev(70, "yang", "T-21", b, "claude_code", "tool", {"tool": "Edit", "ok": True, "file": "hub/hub/stream.py"})
ev(66, "yang", "T-21", b, "claude_code", "tool", test(True, passed=5))
ev(65, "yang", "T-21", None, "mcp", "self_report", report={"percent": 60, "done": ["stream endpoint", "reconnect with Last-Event-ID"],
                                                             "doing": "wiring the board to the stream", "next": ["board uses EventSource", "drop polling"]})
ev(64, "yang", "T-21", b, "claude_code", "turn_end", summary="Reconnects now resume from Last-Event-ID; all 5 stream tests pass.", status="progress")
ev(8, "yang", "T-21", b, "claude_code", "tool", {"tool": "Edit", "ok": True, "file": "hub/hub/static/board.html"})
ev(3, "yang", "T-21", b, "claude_code", "turn_end", summary="Board now opens an EventSource; polling kept as a fallback for now.", status="progress")

# T-22: sourabh, Codex, progress_snapshots migration. Blocked on database rights.
b = "T-22-snapshots-migration"
ev(120, "sourabh", "T-22", b, "codex", "session_start", {"source": "startup"})
ev(116, "sourabh", "T-22", b, "codex", "tool", {"tool": "apply_patch", "ok": True, "file": "hub/migrations/003_progress.sql"})
ev(112, "sourabh", "T-22", b, "codex", "tool", {"tool": "Bash", "ok": None, "cmd": {"kind": "other", "ok": False}})
ev(111, "sourabh", "T-22", b, "codex", "turn_end", summary="Wrote the progress_snapshots migration; applying it failed with a permission error.", status="progress")
ev(60, "sourabh", "T-22", b, "codex", "tool", {"tool": "apply_patch", "ok": True, "file": "hub/migrations/003_progress.sql"})
ev(57, "sourabh", "T-22", b, "codex", "tool", {"tool": "Bash", "ok": None, "cmd": {"kind": "other", "ok": False}})
ev(56, "sourabh", "T-22", None, "mcp", "blocked", report={"reason": "The demo database user is read-only, so the migration can't create tables.", "needs": "access"})
ev(55, "sourabh", "T-22", b, "codex", "turn_end", summary="Stuck: the database user can't create tables; asked the lead for access.", status="blocked")

# T-19: asha, Claude Code, board sign-in. Done in code, PR open, CI green, waiting for review.
b = "T-19-board-signin"
ev(240, "asha", "T-19", b, "claude_code", "session_start", {"source": "startup"})
ev(238, "asha", "T-19", None, "mcp", "task_start", {"title": "Board sign-in with an HttpOnly cookie"})
ev(230, "asha", "T-19", b, "claude_code", "tool", {"tool": "Edit", "ok": True, "file": "hub/hub/team.py"})
ev(220, "asha", "T-19", b, "claude_code", "tool", test(True, passed=7))
ev(219, "asha", "T-19", b, "claude_code", "tool", {"tool": "Bash", "ok": True, "cmd": {"kind": "git", "ok": True}})
ev(218, "asha", "T-19", b, "claude_code", "turn_end", summary="Sign-in sets an HttpOnly cookie; 7 tests pass; committed and pushed.", status="done")
ev(215, "asha", "T-19", None, "github", "pr", {"number": 18, "title": "T-19: board sign-in with an HttpOnly cookie", "state": "open",
                                               "draft": False, "url": None, "author": "asha"}, member_override="github")
ev(205, "asha", "T-19", None, "github", "check", {"name": "ci", "conclusion": "success", "branch": b, "url": None}, member_override="github")

# T-17: yang, Claude Code, commit trailer hook. Merged.
b = "T-17-commit-trailer"
ev(420, "yang", "T-17", b, "claude_code", "session_start", {"source": "startup"})
ev(415, "yang", "T-17", b, "claude_code", "tool", {"tool": "Write", "ok": True, "file": "connector/teamloop/githook.py"})
ev(400, "yang", "T-17", b, "claude_code", "tool", test(True, passed=6))
ev(398, "yang", "T-17", b, "claude_code", "turn_end", summary="prepare-commit-msg hook adds TeamLoop-Task trailers, keeps existing hooks; 6 tests pass.", status="done")
ev(380, "yang", "T-17", None, "github", "pr", {"number": 15, "title": "T-17: commit trailer hook", "state": "merged",
                                               "draft": False, "url": None, "author": "yang"}, member_override="github")

for e in events:
    if e.pop("member_override", None):
        e["member"] = "github"

# Run the real Agent S per task over the events as they'll look when seeded "now".
now = time.time()
for e in events:
    e["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - e["offset_min"] * 60)) + ".000Z"
snapshots = {}
titles = {"T-21": "SSE stream for the board", "T-22": "progress_snapshots migration", "T-19": "Board sign-in with an HttpOnly cookie",
          "T-17": "Commit trailer hook"}
for task, title in titles.items():
    evs = [{k: v for k, v in e.items() if k != "offset_min"} for e in events if e["task"] == task]
    t = time.perf_counter()
    snap = progress.estimate(task, evs, title)
    # evidence ids point at the seeded events: keep them, they're the same ids
    snapshots[task] = snap
    print(f"{task}: {snap['percent']}% {snap['status']} ({snap['model']}, {time.perf_counter() - t:.0f}s, dropped {snap['dropped_uncited']})")

for e in events:
    e.pop("ts")
out = ROOT / "hub" / "hub" / "demo" / "demo.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"built": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "events": events,
                           "snapshots": snapshots}, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", out, len(events), "events")
