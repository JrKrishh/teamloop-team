"""GitHub webhooks -> task events (PLAN.md §9.4). A GitHub App and a plain repo webhook send the same payloads
and the same X-Hub-Signature-256, so one receiver serves both.

Env: GITHUB_WEBHOOK_SECRET (required), HUB_GITHUB_REPOS="owner/repo=room,owner/other=room2".
Tasks come from the TeamLoop-Task trailer on commits, else the branch name (T-14-...), else the PR title.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request

from .safety import sanitize

TASK = re.compile(r"\b([A-Z][A-Z0-9]{0,15}-\d{1,8})\b")
TRAILER = re.compile(r"^TeamLoop-Task:\s*([A-Z][A-Z0-9]{0,15}-\d{1,8})\s*$", re.M)


def task_from(*texts: Optional[str]) -> Optional[str]:
    for t in texts:
        m = TASK.search(t or "")
        if m:
            return m.group(1)
    return None


def _clip(text: Optional[str], n: int = 120) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return sanitize(line[:n])[0]


def to_events(kind: str, p: dict, delivery: str) -> list[dict]:
    """Webhook payload -> TeamLoop events (tool 'github'). Unknown or uninteresting events -> []."""
    out: list[dict] = []

    def add(event_kind: str, task: Optional[str], ts: Optional[str], facts: dict) -> None:
        if not task:
            return
        eid = hashlib.sha256(f"{delivery}:{len(out)}".encode()).hexdigest()[:32]
        out.append({"v": 1, "id": eid, "ts": ts or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tool": "github",
                    "session": None, "kind": event_kind, "task": task, "facts": facts})

    action = p.get("action")
    if kind == "pull_request" and action in ("opened", "reopened", "ready_for_review", "closed", "converted_to_draft"):
        pr = p["pull_request"]
        state = "merged" if pr.get("merged") else pr.get("state")
        add("pr", task_from(pr["head"]["ref"], pr.get("title")), pr.get("updated_at"),
            {"number": pr["number"], "title": _clip(pr.get("title")), "state": state, "draft": bool(pr.get("draft")),
             "url": pr.get("html_url"), "author": (pr.get("user") or {}).get("login")})
    elif kind == "pull_request_review" and action == "submitted":
        pr, review = p["pull_request"], p["review"]
        add("review", task_from(pr["head"]["ref"], pr.get("title")), review.get("submitted_at"),
            {"number": pr["number"], "state": (review.get("state") or "").lower(),
             "reviewer": (review.get("user") or {}).get("login"), "url": review.get("html_url")})
    elif kind == "workflow_run" and action == "completed":
        run = p["workflow_run"]
        add("check", task_from(run.get("head_branch")), run.get("updated_at"),
            {"name": run.get("name"), "conclusion": run.get("conclusion"), "branch": run.get("head_branch"),
             "url": run.get("html_url")})
    elif kind == "check_suite" and action == "completed":
        suite = p["check_suite"]
        add("check", task_from(suite.get("head_branch")), suite.get("updated_at"),
            {"name": (suite.get("app") or {}).get("name"), "conclusion": suite.get("conclusion"),
             "branch": suite.get("head_branch"), "url": None})
    elif kind == "push":
        branch = (p.get("ref") or "").removeprefix("refs/heads/")
        for c in p.get("commits", [])[:20]:
            trailer = TRAILER.search(c.get("message") or "")
            add("commit", trailer.group(1) if trailer else task_from(branch), c.get("timestamp"),
                {"sha": (c.get("id") or "")[:12], "message": _clip(c.get("message")), "branch": branch,
                 "url": c.get("url"), "author": (c.get("author") or {}).get("username")})
    return out


def install(app: FastAPI) -> None:
    conn, lock = app.state.conn, app.state.lock

    def rooms() -> dict[str, str]:
        pairs = (e.split("=", 1) for e in os.getenv("HUB_GITHUB_REPOS", "").split(",") if "=" in e)
        return {repo.strip().lower(): room.strip() for repo, room in pairs}

    @app.post("/v1/github", status_code=202)
    async def github(request: Request, x_hub_signature_256: Optional[str] = Header(default=None),
                     x_github_event: Optional[str] = Header(default=None),
                     x_github_delivery: Optional[str] = Header(default=None)) -> dict:
        secret = os.getenv("GITHUB_WEBHOOK_SECRET")
        if not secret:
            raise HTTPException(503, "GitHub webhooks are not configured on this hub")
        body = await request.body()
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not x_hub_signature_256 or not hmac.compare_digest(expected, x_hub_signature_256):
            raise HTTPException(401, "Bad signature")
        payload = json.loads(body)
        if x_github_event == "ping":
            return {"ok": True, "pong": True}
        room = rooms().get(((payload.get("repository") or {}).get("full_name") or "").lower())
        if not room or not x_github_delivery:
            return {"accepted": 0, "ignored": "repository not linked to a room"}
        events = to_events(x_github_event or "", payload, x_github_delivery)
        now = time.time()
        with lock:
            accepted = sum(conn.execute(
                "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (e["id"], room, "github", e["task"], e["kind"], e["ts"][:32], json.dumps({**e, "member": "github"}), now),
            ).rowcount for e in events)
            conn.commit()
        return {"accepted": accepted, "events": len(events)}  # redeliveries hash to the same ids
