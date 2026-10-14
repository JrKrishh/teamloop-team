"""The usage counter: coding agents' tokens (each turn's facts.usage, counted on the developer's laptop from their
agent's transcript) and Super Agents' own model use, by day, tool, task, model and person. Pure; both hubs can use it.

"Tokens" means new tokens: fresh input + cache writes + output. Cache reads are counted apart: the agent re-reads the
same cached context on every call, so they run 100x larger without being new work.

Per-person numbers go to the lead and to that person only, listed by name: usage is for knowing the cost, not a
ranking (PLAN.md §12.5). Tasks are the unit everyone sees.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

TOOLS = ("claude_code", "codex")
KEYS = ("in", "cw", "cr", "out", "calls")


def tokens(u: dict) -> int:
    return int(u.get("in") or 0) + int(u.get("cw") or 0) + int(u.get("out") or 0)


def _coding() -> dict:
    return {"tokens": 0, "in": 0, "cw": 0, "cr": 0, "out": 0, "calls": 0, "turns": 0}


def _agents() -> dict:
    return {"tokens": 0, "in": 0, "out": 0, "calls": 0}


def _add_turn(acc: dict, u: dict) -> None:
    for k in KEYS:
        acc[k] += int(u.get(k) or 0)
    acc["tokens"] += tokens(u)
    acc["turns"] += 1


def _add_agent(acc: dict, row: dict) -> None:
    acc["in"] += int(row["tokens_in"] or 0)
    acc["out"] += int(row["tokens_out"] or 0)
    acc["calls"] += int(row["calls"] or 0)
    acc["tokens"] = acc["in"] + acc["out"]


def summarize(turns: list[dict], agent_rows: list[dict], *, me: str | None, lead: bool, days: int,
              tz_minutes: int = 0, now: float) -> dict:
    """turns: {user_id, member, task, tool, session, usage, at (epoch s)}; agent_rows: {user_id (None for the team's
    own jobs: progress, digest), member, source, model, calls, tokens_in, tokens_out, at}. Days are local to tz."""
    tz = timezone(timedelta(minutes=tz_minutes))
    today = datetime.fromtimestamp(now, tz).date()
    by_day = {d: {"day": d, "claude_code": 0, "codex": 0, "agents": 0}
              for d in ((today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1))}
    coding, tools, agents, team_jobs = _coding(), {t: _coding() for t in TOOLS}, _agents(), _agents()
    sessions: set = set()
    tasks: dict[str, dict] = {}
    models: dict[str, int] = {}
    sources: dict[str, int] = {}
    people: dict[str, dict] = {}

    def person(uid, name) -> dict:
        return people.setdefault(str(uid), {"user_id": str(uid), "name": name or "someone", "coding": _coding(),
                                            "agents": _agents(), "sessions": set()})

    for t in turns:
        day = datetime.fromtimestamp(t["at"], tz).date().isoformat()
        u = t.get("usage") or {}
        if day not in by_day or not isinstance(u, dict):
            continue
        n = tokens(u)
        _add_turn(coding, u)
        sessions.add(t.get("session"))
        if t.get("tool") in tools:
            _add_turn(tools[t["tool"]], u)
            by_day[day][t["tool"]] += n
        if t.get("task"):
            k = tasks.setdefault(t["task"], {"task": t["task"], "tokens": 0, "turns": 0, "people": set()})
            k["tokens"] += n
            k["turns"] += 1
            k["people"].add(t.get("member"))
        model = str(u.get("model") or t.get("tool") or "unknown")
        models[model] = models.get(model, 0) + n
        if t.get("user_id"):
            p = person(t["user_id"], t.get("member"))
            _add_turn(p["coding"], u)
            p["sessions"].add(t.get("session"))

    for a in agent_rows:
        day = datetime.fromtimestamp(a["at"], tz).date().isoformat()
        if day not in by_day:
            continue
        n = int(a["tokens_in"] or 0) + int(a["tokens_out"] or 0)
        _add_agent(agents, a)
        by_day[day]["agents"] += n
        sources[a["source"]] = sources.get(a["source"], 0) + n
        model = str(a.get("model") or "nemotron").split(":")[-1]
        models[model] = models.get(model, 0) + n
        if a.get("user_id"):
            _add_agent(person(a["user_id"], a.get("member"))["agents"], a)
        else:
            _add_agent(team_jobs, a)

    seen = [p for p in people.values() if lead or p["user_id"] == me]
    return {
        "days": days, "today": today.isoformat(), "scope": "team" if lead else "you",
        "total": coding["tokens"] + agents["tokens"],
        "coding": {**coding, "sessions": len(sessions - {None})},
        "tools": tools,
        "agents": {**agents, "sources": sources, "team_jobs": team_jobs},
        "by_day": list(by_day.values()),
        "tasks": [{**k, "people": sorted(x for x in k["people"] if x)}
                  for k in sorted(tasks.values(), key=lambda k: -k["tokens"])][:30],
        "models": [{"model": m, "tokens": n} for m, n in sorted(models.items(), key=lambda x: -x[1]) if n][:12],
        "people": [{"user_id": p["user_id"], "name": p["name"], "you": p["user_id"] == me, "coding": p["coding"],
                    "agents": p["agents"], "sessions": len(p["sessions"] - {None}),
                    "total": p["coding"]["tokens"] + p["agents"]["tokens"]}
                   for p in sorted(seen, key=lambda p: p["name"].lower())],
    }
