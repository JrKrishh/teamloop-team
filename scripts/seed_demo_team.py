"""The judges' demo team on a hub's database: "Acme Web (demo)", with a lead (you), two made-up teammates (Asha and
Ravi), a week of their coding sessions and Agent S progress (from the website's demo, hub/hub/demo/demo.json), the
board's to-dos with owners and deadlines, pinned decisions, the steps a lead approves, prompts into teammates'
sessions on record, and Super Agents usage. Re-runnable: it replaces the demo team it made before. Times are relative
to now, so run it again shortly before judging (1-15 Dec) to keep the demo fresh.

    DATABASE_URL=postgresql://... python scripts/seed_demo_team.py --lead you@example.com [--judge judges@example.com]

Both accounts must have signed in to Super Agents once. --judge joins as a second lead, so judges see what a lead
sees. Usage rows are made up only for Asha, Ravi and the team, never for real accounts: those count against a
person's daily model allowance.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

NAME = "Acme Web (demo)"
DEMO = Path(__file__).resolve().parents[1] / "hub" / "hub" / "demo" / "demo.json"
LATER = {"T-17": 2 * 1440, "T-19": 1440}  # older work, so the usage chart covers days, not hours
USAGE = {"T-21": (410_000, 52_000, 14_000), "T-22": (260_000, 31_000, 9_000), "T-19": (380_000, 44_000, 12_000),
         "T-17": (190_000, 22_000, 6_000)}
SUPER = "nebius:nvidia/nemotron-3-super-120b-a12b"


def account(c, email: str) -> tuple[str, str]:
    """(user id, name) of someone who has signed in to this hub, by email."""
    row = (c.execute("select user_id, name from memberships where lower(email) = lower(%s) limit 1", (email,)).fetchone()
           or c.execute("select user_id, name from hub_sessions where lower(email) = lower(%s) order by created_at desc limit 1",
                        (email,)).fetchone())
    if not row:
        sys.exit(f"{email} hasn't signed in to Super Agents on this hub yet: sign in once, then run this again.")
    return str(row[0]), row[1] or email.split("@")[0]


def seed(c, lead: tuple[str, str], judge: tuple[str, str] | None, now: datetime) -> str:
    rnd = random.Random(54)
    raw = DEMO.read_text(encoding="utf-8")
    demo = json.loads(raw.replace("sourabh", "ravi").replace("Sourabh", "Ravi").replace("teamloop-team", "acme-web"))
    asha = (str(uuid.uuid5(uuid.NAMESPACE_DNS, "asha.demo.superagents")), "Asha")
    ravi = (str(uuid.uuid5(uuid.NAMESPACE_DNS, "ravi.demo.superagents")), "Ravi")
    people = {"yang": lead, "asha": asha, "ravi": ravi}  # the demo's own lead is "yang": the lead running this takes that part

    for (tid,) in c.execute("select id from teams where name = %s and created_by = %s", (NAME, lead[0])).fetchall():
        c.execute("delete from teams where id = %s", (tid,))
    team = str(c.execute("insert into teams (name, created_by) values (%s, %s) returning id", (NAME, lead[0])).fetchone()[0])
    members = [(lead, None, "lead"), (asha, "asha@example.com", "member"), (ravi, "ravi@example.com", "member")]
    if judge and judge[0] != lead[0]:
        members.append((judge, None, "lead"))
    for (uid, name), email, role in members:
        c.execute("insert into memberships (team_id, user_id, email, name, role) values (%s, %s, %s, %s, %s)",
                  (team, uid, email, name, role))

    for e in demo["events"]:
        if e["kind"] in ("pr", "review", "check"):  # GitHub's webhook events: only a self-hosted hub gets them
            continue
        e = dict(e)
        at = now - timedelta(minutes=e.pop("offset_min") + LATER.get(e.get("task"), 0))
        uid, name = people.get(e["member"], (None, e["member"]))
        e["member"] = name
        e["ts"] = at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if e["kind"] == "turn_end" and e.get("task") in USAGE:
            i, cw, o = USAGE[e["task"]]
            e.setdefault("facts", {})["usage"] = {"in": int(i * rnd.uniform(.6, 1.4)), "cw": int(cw * rnd.uniform(.6, 1.4)),
                                                  "out": int(o * rnd.uniform(.6, 1.4))}
        c.execute("insert into events (team_id, id, user_id, member, task, kind, ts, body, received_at)"
                  " values (%s, %s, %s, %s, %s, %s, %s, %s, %s)", (team, e["id"], uid, name, e.get("task"), e["kind"], e["ts"], Jsonb(e), at))
    for task, snap in demo["snapshots"].items():
        c.execute("insert into snapshots (team_id, task, created_at, body) values (%s, %s, %s, %s)", (team, task, now, Jsonb(snap)))

    day = lambda n: (now + timedelta(days=n)).date()  # noqa: E731
    for task, title, owner, state, due in [
        ("T-17", "Commit trailer hook", "yang", "closed", None),
        ("T-19", "Board sign-in with an HttpOnly cookie", "asha", "open", day(1)),
        ("T-21", "SSE stream for the board", "yang", "open", day(2)),
        ("T-22", "Progress snapshots table", "ravi", "open", day(1)),
        ("T-23", "Rate limits for the public API", "asha", "open", day(3)),
        ("T-24", "Retry failed payments at checkout", "ravi", "open", day(5)),
        ("T-25", "Publish the v0.3 release", "yang", "open", day(4)),
    ]:
        uid, name = people[owner]
        c.execute("insert into tasks (team_id, task, title, owner_id, owner_name, state, created_by, due)"
                  " values (%s, %s, %s, %s, %s, %s, %s, %s)", (team, task, title, uid, name, state, lead[0], due))

    for text, who, role, ago in [("Postgres is our only database: no new data stores without a lead's yes.", "yang", "lead", 300),
                                 ("Every API change ships with a test.", "asha", "member", 120)]:
        uid, name = people[who]
        c.execute("insert into decisions (team_id, text, by_user, by_name, by_role, created_at) values (%s, %s, %s, %s, %s, %s)",
                  (team, text, uid, name, role, now - timedelta(minutes=ago)))
    c.execute("insert into team_rules (team_id, lead_approves, updated_by) values (%s, %s, %s)", (team, ["push", "pr", "shell"], lead[0]))
    c.execute("insert into approvals (team_id, from_user, from_name, rule, tool, what, detail, created_at)"
              " values (%s, %s, %s, %s, %s, %s, %s, %s)",
              (team, asha[0], "Asha", "push", "git_push", "Push the branch T-23-rate-limits to GitHub",
               "git push origin T-23-rate-limits  (3 commits: limiter middleware, 429 responses, tests)", now - timedelta(minutes=2)))

    c.execute("insert into session_access (team_id, user_id, mode, access, daily_tokens) values"
              " (%s, %s, 'ask', 'read', 200000), (%s, %s, 'auto', 'read', 300000)", (team, ravi[0], team, asha[0]))
    for frm, to, session, tool, task, prompt, result, tokens, ago in [
        ("yang", "ravi", "ravi-T-22", "codex", "T-22", "Which migration needs CREATE TABLE? Paste the exact error.",
         "0007_progress_snapshots.sql: permission denied for schema public (CREATE TABLE). The app's database user has no "
         "CREATE on public.", 18_400, 50),
        ("asha", "yang", "yang-T-21", "claude_code", "T-21", "What does a stream event look like? I'll match it in the sign-in redirect.",
         "Each event is `event: board` with JSON data {task, status, percent}; reconnects resume from Last-Event-ID.", 9_200, 25)]:
        (fu, fn), (tu, tn) = people[frm], people[to]
        at = now - timedelta(minutes=ago)
        c.execute("insert into session_prompts (team_id, from_user, from_name, to_user, to_name, session, tool, repo, task, prompt,"
                  " access, status, decided_by, result, tokens, created_at, decided_at, finished_at) values"
                  " (%s, %s, %s, %s, %s, %s, %s, 'acme-web', %s, %s, 'read', 'done', 'owner', %s, %s, %s, %s, %s)",
                  (team, fu, fn, tu, tn, session, tool, task, prompt, result, tokens, at, at + timedelta(seconds=40), at + timedelta(minutes=2)))

    for d in range(7):  # Super Agents' own model use, for the usage view: the made-up teammates' and the team's only
        for uid, name in (asha, ravi):
            for source, lo, hi in [("app", 40_000, 320_000), ("ask", 6_000, 40_000)]:
                if rnd.random() < .85:
                    c.execute("insert into agent_usage (team_id, user_id, member, source, model, calls, tokens_in, tokens_out, at)"
                              " values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                              (team, uid, name, source, SUPER, rnd.randint(4, 40), rnd.randint(lo, hi), rnd.randint(lo // 20, hi // 15),
                               now - timedelta(days=d, hours=rnd.uniform(0, 8))))
        c.execute("insert into agent_usage (team_id, user_id, member, source, model, calls, tokens_in, tokens_out, at)"
                  " values (%s, null, null, 'progress', %s, %s, %s, %s, %s)",
                  (team, SUPER, rnd.randint(8, 30), rnd.randint(30_000, 120_000), rnd.randint(3_000, 9_000), now - timedelta(days=d, hours=2)))
    return team


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lead", required=True, help="your sign-in email: you lead the demo team")
    ap.add_argument("--judge", help="the judges' sign-in email: they join as a second lead")
    args = ap.parse_args()
    url = os.environ.get("DATABASE_URL") or sys.exit("Set DATABASE_URL to the hub's database first.")
    with psycopg.connect(url) as c:
        lead = account(c, args.lead)
        judge = account(c, args.judge) if args.judge else None
        team = seed(c, lead, judge, datetime.now(timezone.utc))
    print(f"{NAME}: {team} | lead {lead[1]}" + (f", judges' account {judge[1]}" if judge else " | no judges' account yet"))


if __name__ == "__main__":
    main()
