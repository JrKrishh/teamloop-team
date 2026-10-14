"""Built-in tools, in groups an agent can have switched on or off: team, files, terminal, browser (skills always).

kind: "read" runs without asking; "change" follows the mode (Manual asks, Auto runs, Plan queues); "ask" always asks
(shell commands, like Claude Code's Bash). File tools only reach the repos connected on This laptop."""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import laptop
from . import mcpman

MAX_TEXT = 20_000
TASK_ID = re.compile(r"^[A-Z][A-Z0-9]{0,15}-\d{1,8}$")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".turbo", "target"}


@dataclass
class Builtin:
    name: str
    group: str
    kind: str
    description: str
    params: dict = field(default_factory=dict)
    required: tuple = ()
    run: Callable | None = None

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                "parameters": {"type": "object", "properties": self.params, "required": list(self.required)}}}


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit} more characters)"


# ---- files: only inside connected repos ------------------------------------------------------------------------
def roots() -> dict[str, Path]:
    return {r["name"]: Path(r["path"]) for r in laptop.status()["repos"] if r["ok"]}


def resolve(path: str) -> Path:
    """'acme-web/src/app.ts' or an absolute path inside a connected repo -> the real path; anything else is refused."""
    rs = roots()
    p = (path or "").strip().replace("\\", "/")
    head, _, rest = p.partition("/")
    target = (rs[head] / rest) if head in rs else Path(p)
    target = target.resolve()
    for root in rs.values():
        root = root.resolve()
        if target == root or root in target.parents:
            return target
    raise PermissionError("Only files inside the repos connected on This laptop can be used")


def display(p: Path) -> str:
    for name, root in roots().items():
        root = root.resolve()
        if p == root or root in p.parents:
            return f"{name}/{p.relative_to(root).as_posix()}".rstrip("/.")
    return str(p)


def list_files(ctx, path: str = "") -> str:
    if not path.strip():
        rs = roots()
        return "\n".join(f"{n}/   ({p})" for n, p in rs.items()) or "No repos connected yet (This laptop → Connect a repo)."
    d = resolve(path)
    if not d.is_dir():
        raise NotADirectoryError(display(d))
    items = sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    lines = [f"{p.name}/" if p.is_dir() else f"{p.name}  {p.stat().st_size} B" for p in items if p.name not in SKIP_DIRS][:300]
    return f"{display(d)}/\n" + "\n".join(lines)


def read_file(ctx, path: str, start_line: int = 1, end_line: int = 0) -> str:
    f = resolve(path)
    if f.stat().st_size > 2_000_000:
        raise ValueError("That file is over 2 MB")
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, int(start_line or 1))
    end = min(len(lines), int(end_line) if end_line else start + 1999)
    body = "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(start, end + 1))
    return _clip(f"{display(f)} (lines {start}-{end} of {len(lines)})\n{body}", 100_000)


def search_files(ctx, query: str, path: str = "") -> str:
    q = query.lower()
    bases = [resolve(path)] if path.strip() else [r.resolve() for r in roots().values()]
    hits = []
    for base in bases:
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                fp = Path(dirpath) / name
                try:
                    if fp.stat().st_size > 1_000_000:
                        continue
                    for n, line in enumerate(fp.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
                        if q in line.lower():
                            hits.append(f"{display(fp)}:{n}: {line.strip()[:200]}")
                            if len(hits) >= 100:
                                return "\n".join(hits) + "\n… (stopped at 100 matches)"
                except (UnicodeDecodeError, OSError):
                    continue
    return "\n".join(hits) or "No matches."


def write_file(ctx, path: str, content: str) -> str:
    f = resolve(path)
    f.parent.mkdir(parents=True, exist_ok=True)
    existed = f.exists()
    f.write_text(content, encoding="utf-8")
    return f"{'Updated' if existed else 'Created'} {display(f)} ({len(content)} characters)"


# ---- terminal --------------------------------------------------------------------------------------------------
def run_command(ctx, command: str, cwd: str = "") -> str:
    where = resolve(cwd) if cwd.strip() else (next(iter(roots().values()), Path.home()))
    shell = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command] if sys.platform == "win32" else ["bash", "-lc", command]
    try:
        r = subprocess.run(shell, cwd=where, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "Timed out after 120 s."
    out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
    return _clip(f"$ {command}\n(exit {r.returncode}, in {display(Path(where).resolve())})\n{out.strip()}")


# ---- browser ---------------------------------------------------------------------------------------------------
_SCRIPT = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def page_text(raw: str) -> str:
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    text = _TAG.sub(" ", _SCRIPT.sub(" ", raw))
    text = re.sub(r"[ \t\r\f\v]+", " ", html.unescape(text))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return (f"# {html.unescape(title.group(1).strip())}\n\n" if title else "") + text


def fetch_url(ctx, url: str) -> str:
    if not url.startswith(("http://", "https://")):
        raise ValueError("Only http and https pages")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SuperAgents", "Accept": "text/html,text/plain,*/*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read(2_000_000)
        kind = r.headers.get("Content-Type", "")
    text = raw.decode("utf-8", errors="replace")
    return _clip(f"{url}\n\n" + (page_text(text) if "html" in kind or text.lstrip().startswith("<") else text))


def open_in_browser(ctx, url: str) -> str:
    if not url.startswith(("http://", "https://")):
        raise ValueError("Only http and https pages")
    ctx.emit("browser", url=url)
    return f"Opened {url} in the browser panel."


# ---- skills ----------------------------------------------------------------------------------------------------
def load_skill(ctx, name: str) -> str:
    s = ctx.skills.get(name)
    if not s:
        raise KeyError(f"No skill named {name}")
    files = s.files()
    return _clip(s.body() + (f"\n\nFiles in this skill (read with read_skill_file): {', '.join(files)}" if files else ""), 60_000)


def read_skill_file(ctx, name: str, file: str) -> str:
    s = ctx.skills.get(name)
    if not s:
        raise KeyError(f"No skill named {name}")
    return _clip(s.read(file), 60_000)


# ---- team (the hub, with this person's session) ----------------------------------------------------------------
def due_text(due: str | None) -> str:
    if not due:
        return ""
    import datetime

    days = (datetime.date.fromisoformat(due) - datetime.date.today()).days
    when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days" if days > 1 else f"{-days} days late"
    return f"due {due} ({when})"


def team_board(ctx) -> str:
    b = ctx.hub("GET", "board")
    lines = []
    for t in b.get("tasks", []):
        p = t.get("progress") or {}
        bits = [f"{t['task']} [{t['status']}] {t.get('title') or ''}", f"owner {t['owner']}" if t.get("owner") else "",
                due_text(t.get("due")),
                f"people {', '.join(t.get('members') or [])}" if t.get("members") else "",
                f"Agent S {p['percent']}%" if p.get("percent") is not None else ""]
        for key in ("blockers", "done", "doing", "next"):
            items = [i["text"] for i in p.get(key) or []][:4]
            if items:
                bits.append(f"{key}: {'; '.join(items)}")
        lines.append(" · ".join(x for x in bits if x))
    people = ", ".join(f"{m['name']}{' (active)' if m.get('active') else ''}" for m in b.get("members", []))
    return f"Team {b.get('room')}. Members: {people or 'none'}\n" + ("\n".join(lines) or "No tasks yet.")


def team_ask(ctx, question: str) -> str:
    r = ctx.hub("POST", "ask", {"question": question})
    return json.dumps({"answer": r.get("answer"), "citations": r.get("citations", []), "unknowns": r.get("unknowns", [])})


def team_task(ctx, task: str) -> str:
    d = ctx.hub("GET", f"tasks/{urllib.parse.quote(task)}")
    tl = "\n".join(f"{e.get('ts', '')[11:16]} {e['member']}: {e['line']}" for e in d.get("timeline", [])[:40])
    return f"{d['task']} [{d['status']}] {d.get('title') or ''}\n{tl or 'No sessions yet.'}"


def _k(n: int) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else str(n)


def team_usage(ctx, days: int = 7) -> str:
    u = ctx.hub("GET", f"usage?days={max(1, min(int(days or 7), 30))}")
    c, a = u["coding"], u["agents"]
    lines = [f"Last {u['days']} days (tokens = fresh input + cache writes + output; cache reads apart):",
             f"Coding agents: {_k(c['tokens'])} tokens over {c['turns']} turns in {c['sessions']} sessions "
             f"(Claude Code {_k(u['tools']['claude_code']['tokens'])}, Codex {_k(u['tools']['codex']['tokens'])}; "
             f"cache reads {_k(c['cr'])})",
             f"Super Agents (Nemotron): {_k(a['tokens'])} tokens over {a['calls']} calls"]
    if u["tasks"]:
        lines.append("By task: " + "; ".join(f"{t['task']} {_k(t['tokens'])} ({', '.join(t['people'])})" for t in u["tasks"][:10]))
    if u["people"]:
        who = "By person" if u["scope"] == "team" else "You"
        lines.append(f"{who}: " + "; ".join(f"{p['name']} {_k(p['total'])}" for p in u["people"]))
    lines.append("By day: " + ", ".join(f"{d['day'][5:]} {_k(d['claude_code'] + d['codex'] + d['agents'])}" for d in u["by_day"]))
    return "\n".join(lines)


def create_task(ctx, title: str, owner: str = "", task: str = "", due: str = "") -> str:
    r = ctx.hub("POST", "tasks", {"title": title, "owner": owner or None, "task": task, "due": due or None})
    return (f"Created {r['task']}: {r['title']}" + (f" (owner {r['owner']})" if r.get("owner") else "")
            + (f", {due_text(r['due'])}" if r.get("due") else ""))


def set_deadline(ctx, task: str, due: str) -> str:
    if due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
        raise ValueError("Give the deadline as YYYY-MM-DD, or empty to clear it")
    r = ctx.hub("PATCH", f"tasks/{urllib.parse.quote(task)}", {"due": due})
    return f"{r['task']} is {due_text(r['due'])}" if r.get("due") else f"{r['task']} has no deadline now"


# ---- Super Team: teammates' coding sessions -------------------------------------------------------------------
TOOL_NAMES = {"claude_code": "Claude Code", "codex": "Codex"}


def _ago(t: float) -> str:
    import time

    m = max(0, int((time.time() - t) // 60))
    return "just now" if m < 1 else f"{m} min ago" if m < 60 else f"{m // 60} h ago"


def team_sessions(ctx) -> str:
    d = ctx.hub("GET", "sessions")
    lines = []
    for x in d["sessions"]:
        if x["mine"]:
            continue
        rules = "off" if x["mode"] == "off" else (("asks them first" if x["mode"] == "ask" else "runs automatically")
                                                  + (", read only" if x["access"] == "read" else ", can edit"))
        limit = f", you've used {x['used_today']:,} of {x['daily_tokens']:,} tokens today" if x["daily_tokens"] else ""
        lines.append(f"{x['session']}: {x['owner']['name']}'s {TOOL_NAMES.get(x['tool'], x['tool'])} session in "
                     f"{x['repo'] or 'a repo'}{' on ' + x['task'] if x['task'] else ''}, {'active now' if x['active'] else 'last active ' + _ago(x['last'])}"
                     f", {x['turns']} turns. Prompts: {rules}{limit}. Their Super Agents is {'open' if x['app_online'] else 'closed'}.")
    return "\n".join(lines) or "No teammate has a coding session from the last day."


def prompt_session(ctx, prompt: str, session: str = "", member: str = "") -> str:
    if not session:
        d = ctx.hub("GET", "sessions")
        mine = [x for x in d["sessions"] if not x["mine"] and x["owner"]["name"].lower() == member.strip().lower()]
        if not mine:
            raise ValueError(f"No recent session of {member or 'that teammate'}; team_sessions lists who has one")
        session = mine[0]["session"]
    p = ctx.hub("POST", "prompts", {"session": session, "prompt": prompt})
    who, where = p["to"]["name"], p["task"] or p["repo"] or "their repo"
    rights = "read only" if p["access"] == "read" else "can edit"
    if p["status"] == "pending":
        return (f"Sent to {who}'s {TOOL_NAMES.get(p['tool'], p['tool'])} session ({where}); {who} decides first ({rights}). "
                f"Prompt id {p['id']}: read the answer later with session_prompt.")
    return f"Sent to {who}'s session ({where}); their rules run it automatically ({rights}). Prompt id {p['id']}."


def session_prompt(ctx, id: str, wait: float = 30) -> str:
    """Waits a little for a prompt that's allowed or running (the owner's rules run it automatically), never for a
    person's decision."""
    import time

    if not re.fullmatch(r"[0-9a-f-]{36}", id or ""):
        raise ValueError("That isn't a prompt id")
    p, until = ctx.hub("GET", f"prompts/{id}"), time.time() + wait
    while p["status"] in ("approved", "running") and time.time() < until and not getattr(ctx, "cancelled", False):
        time.sleep(3)
        p = ctx.hub("GET", f"prompts/{id}")
    head = (f"{p['from']['name']} → {p['to']['name']}'s {TOOL_NAMES.get(p['tool'], p['tool'])} session: {p['status']}"
            + (f", {p['tokens']:,} tokens" if p["tokens"] else ""))
    return head + (f"\nAnswer:\n{p['result']}" if p.get("result") else "")


# ---- code review: diffs to read ------------------------------------------------------------------------------
def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=30, stdin=subprocess.DEVNULL)


def git_diff(ctx, repo: str = "", base: str = "") -> str:
    rs = roots()
    path = rs.get(repo) if repo else (next(iter(rs.values())) if len(rs) == 1 else None)
    if not path:
        raise ValueError(f"Say which repo: {', '.join(rs) or 'connect one on This laptop first'}")
    if base and not re.fullmatch(r"[A-Za-z0-9._/~^-]{1,100}", base):
        raise ValueError("That base doesn't look like a branch or a commit")
    if _git(path, "rev-parse", "--verify", "HEAD").returncode != 0:
        return f"{display(path.resolve())} has no commits yet.\n" + _git(path, "status", "--short").stdout
    span = [f"{base}...HEAD"] if base else ["HEAD"]
    diff = _git(path, "diff", *span)
    if diff.returncode != 0:
        raise RuntimeError(diff.stderr.strip()[:300] or "git diff failed")
    stat = _git(path, "diff", "--stat", *span).stdout.strip()
    log = _git(path, "log", "--oneline", "-8", *([f"{base}..HEAD"] if base else [])).stdout.strip()
    what = f"changes on this branch since {base}" if base else "uncommitted changes"
    return _clip(f"{display(path.resolve())}: {what}\n{stat or '(none)'}\n\nCommits:\n{log}\n\n{diff.stdout}", 80_000)


def _github_token() -> str | None:
    for c in mcpman.load():
        if c.get("preset") == "github" and c.get("enabled", True):
            return (c.get("headers") or {}).get("Authorization")
    return None


def github_pr(ctx, repo: str, number: int) -> str:
    repo = repo.strip().removeprefix("https://github.com/").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repo):
        raise ValueError("Use owner/repo, for example acme/web")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "SuperAgents"}
    if _github_token():
        headers["Authorization"] = _github_token()

    def get(url: str):
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            return json.loads(r.read())

    n = int(number)
    pr = get(f"https://api.github.com/repos/{repo}/pulls/{n}")
    files = get(f"https://api.github.com/repos/{repo}/pulls/{n}/files?per_page=100")
    out = [f"{repo}#{n} {pr['title']} by {pr['user']['login']} ({pr['state']}{', draft' if pr.get('draft') else ''}): "
           f"{pr['head']['ref']} → {pr['base']['ref']}, {pr.get('changed_files', len(files))} files", (pr.get("body") or "")[:3000], ""]
    for f in files:
        out.append(f"--- {f['filename']} ({f['status']}, +{f['additions']} -{f['deletions']})\n{f.get('patch') or '(no text diff)'}")
    return _clip("\n".join(out), 80_000)



def assign_task(ctx, task: str, owner: str) -> str:
    r = ctx.hub("PATCH", f"tasks/{urllib.parse.quote(task)}", {"owner": owner})
    return f"{r['task']} is now owned by {r['owner'] or 'nobody'}"


def close_task(ctx, task: str) -> str:
    r = ctx.hub("PATCH", f"tasks/{urllib.parse.quote(task)}", {"state": "closed"})
    return f"Closed {r['task']}"


def start_task(ctx, task: str, title: str = "", repo: str = "") -> str:
    if not TASK_ID.match(task):
        raise ValueError("A task id looks like T-23")
    rs = roots()
    if repo and repo not in rs:
        raise ValueError(f"{repo} isn't connected. Connected repos: {', '.join(rs) or 'none'}")
    path = str(rs[repo]) if repo else (str(next(iter(rs.values()))) if len(rs) == 1 else "")
    if not path:
        raise ValueError(f"Say which repo: {', '.join(rs) or 'connect one on This laptop first'}")
    laptop.start_task(path, task, title)
    return f"This laptop's sessions in {Path(path).name} now report on {task}"


S = {"type": "string"}
I = {"type": "integer"}
BUILTINS = [
    Builtin("team_board", "team", "read", "The team's board: every task with status, owner, people, Agent S progress and its done/doing/next/blockers."),
    Builtin("team_ask", "team", "read", "Ask the team's session history a question. The answer comes with citations (event ids); claims about what the team did must come from here.",
            {"question": S}, ("question",), team_ask),
    Builtin("team_task", "team", "read", "One task's full timeline from the developers' coding sessions.", {"task": S}, ("task",), team_task),
    Builtin("team_usage", "team", "read", "AI usage: coding agents' and Super Agents' tokens by task, tool, day and person "
            "(the lead sees everyone; a member, themself). days: 1-30, default 7.", {"days": I}, (), team_usage),
    Builtin("create_task", "team", "change", "Add a task to the board. owner: a member's name or empty. task: an id like T-23, or empty to "
            "number it. due: a deadline as YYYY-MM-DD, or empty.", {"title": S, "owner": S, "task": S, "due": S}, ("title",), create_task),
    Builtin("set_deadline", "team", "change", "Set a task's deadline (YYYY-MM-DD), or clear it with an empty due.",
            {"task": S, "due": S}, ("task", "due"), set_deadline),
    Builtin("team_sessions", "team", "read", "Teammates' Claude Code and Codex sessions from the last day: repo, task, how active, "
            "and each owner's rules for prompts from teammates (off, asks first, automatic; read only or can edit; daily tokens).",
            {}, (), team_sessions),
    Builtin("prompt_session", "team", "change", "Send a prompt into a teammate's coding session (by session id, or by member name for "
            "their latest). Their rules decide: it may wait for them to allow it. It runs as a copy of their session on their "
            "laptop and the answer comes back; every prompt is on the team's record.", {"prompt": S, "session": S, "member": S},
            ("prompt",), prompt_session),
    Builtin("session_prompt", "team", "read", "The status and answer of a prompt sent into a teammate's session.", {"id": S}, ("id",),
            session_prompt),
    Builtin("assign_task", "team", "change", "Give a task to a member (by name).", {"task": S, "owner": S}, ("task", "owner"), assign_task),
    Builtin("close_task", "team", "change", "Close a task that is done or dropped.", {"task": S}, ("task",), close_task),
    Builtin("start_task", "team", "change", "Make a task the one this laptop's coding sessions report on, in a connected repo.",
            {"task": S, "title": S, "repo": S}, ("task",), start_task),
    Builtin("list_files", "files", "read", "List a folder in a connected repo ('' lists the repos; paths look like repo-name/src).",
            {"path": S}, (), list_files),
    Builtin("read_file", "files", "read", "Read a text file in a connected repo, with line numbers.",
            {"path": S, "start_line": I, "end_line": I}, ("path",), read_file),
    Builtin("search_files", "files", "read", "Find lines containing some text in the connected repos (or under path).",
            {"query": S, "path": S}, ("query",), search_files),
    Builtin("write_file", "files", "change", "Create or overwrite a text file in a connected repo with the full new content.",
            {"path": S, "content": S}, ("path", "content"), write_file),
    Builtin("git_diff", "files", "read", "A connected repo's diff for review: uncommitted changes, or with base (a branch or commit) "
            "everything on this branch since it, with the commits.", {"repo": S, "base": S}, (), git_diff),
    Builtin("run_command", "terminal", "ask", "Run a shell command on this laptop (PowerShell on Windows) in a connected repo; returns output and exit code.",
            {"command": S, "cwd": S}, ("command",), run_command),
    Builtin("fetch_url", "browser", "read", "Read a web page as text.", {"url": S}, ("url",), fetch_url),
    Builtin("github_pr", "browser", "read", "A GitHub pull request for review: title, description and each file's diff. Public repos "
            "need nothing; private ones use the GitHub connector's token if you added it.", {"repo": S, "number": I}, ("repo", "number"),
            github_pr),
    Builtin("open_in_browser", "browser", "read", "Show a page to the person in the app's browser panel.", {"url": S}, ("url",), open_in_browser),
    Builtin("load_skill", "skills", "read", "Read a skill's full instructions by name.", {"name": S}, ("name",), load_skill),
    Builtin("read_skill_file", "skills", "read", "Read a file that a skill refers to.", {"name": S, "file": S}, ("name", "file"), read_skill_file),
]
BUILTINS[0].run = team_board
BY_NAME = {b.name: b for b in BUILTINS}
