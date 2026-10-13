"""Memory for Super Agents' agents: notes they keep, and recall over what happened before.

- Notes: short, lasting facts you or an agent saved (a preference, a decision, how a project works), in
  ~/.teamloop/memory/notes.json. Every agent sees the shared notes and its own, in every turn. Secrets are refused.
- Recall: full-text search on this laptop (SQLite FTS5, stemmed, ranked by bm25) over the notes, past Super Agents
  chats and, unless you switch it off, your own Claude Code and Codex sessions in every project here: the prompts you
  typed and the agents' replies, never tool output or thinking. The index fills in the background, newest sessions
  first, reading only what's new in each file since last time.

What a search finds goes to the model as a tool result, like any tool's output, with secrets hidden first. The index
itself never leaves this laptop.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from teamloop import redact, spool

NOTES_MAX, NOTE_LEN, CHUNK, READ_BLOCK = 300, 600, 1500, 8_000_000
STOP = set("a an and are as at be but by can did do does for from has have how i if in into is it its me my not of on or "
           "our so that the their them then there these they this to was we were what when where which who why will with "
           "you your".split())
KINDS = {"notes": ("note",), "chats": ("chat",), "sessions": ("claude_code", "codex")}
_lock = threading.Lock()


def _dir() -> Path:
    return spool.home() / "memory"


def _read(name: str, default):
    try:
        return json.loads((_dir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(name: str, data) -> None:
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"{name}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, d / name)


# ---- notes -------------------------------------------------------------------------------------------------------
def notes() -> list[dict]:
    return [n for n in _read("notes.json", []) if isinstance(n, dict) and n.get("id") and n.get("text")]


def add_note(text: str, scope: str = "all", by: str = "") -> dict:
    text = " ".join(str(text).split())[:NOTE_LEN]
    if not text:
        raise ValueError("A note needs some text")
    if redact.redact(text) != text:
        raise ValueError("That looks like a secret; notes never keep secrets")
    with _lock:
        have = notes()
        same = next((n for n in have if n["text"].lower() == text.lower() and n.get("scope") == scope), None)
        if same:
            return same
        note = {"id": "n" + secrets.token_hex(3), "text": text, "scope": scope, "by": by, "at": time.time()}
        _write("notes.json", (have + [note])[-NOTES_MAX:])
    return note


def delete_note(note_id: str) -> bool:
    with _lock:
        have = notes()
        keep = [n for n in have if n["id"] != note_id]
        if len(keep) == len(have):
            return False
        _write("notes.json", keep)
    return True


def notes_for(agent_id: str) -> list[dict]:
    return [n for n in notes() if n.get("scope") in ("all", agent_id)]


def settings() -> dict:
    return {"sessions": True, **_read("settings.json", {})}


def set_settings(**fields) -> dict:
    s = {**settings(), **fields}
    _write("settings.json", s)
    return s


# ---- the index ---------------------------------------------------------------------------------------------------
def claude_root() -> Path:
    return Path.home() / ".claude" / "projects"


def codex_root() -> Path:
    return Path.home() / ".codex" / "sessions"


def _epoch(ts) -> float | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _chunks(text: str) -> list[str]:
    text = text.strip()
    return [text[i:i + CHUNK] for i in range(0, min(len(text), CHUNK * 4), CHUNK)] if text else []


def _spoken(text: str) -> bool:
    """A prompt a person typed, not a tool's injected text (system reminders, command output, interruptions)."""
    t = text.lstrip()
    return bool(t) and not t.startswith(("<", "[Request interrupted", "Caveat:"))


def _claude_line(raw: bytes) -> dict | None:
    if b'"tool_result"' in raw or (b'"type":"assistant"' in raw and b'"type":"text"' not in raw):
        return None  # tool output and tool calls: skipped without parsing
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    kind = d.get("type")
    out = {"cwd": d.get("cwd"), "at": _epoch(d.get("timestamp"))}
    if kind in ("custom-title", "ai-title", "summary"):
        return {**out, "title": d.get("customTitle") or d.get("aiTitle") or d.get("title") or d.get("summary")}
    msg = d.get("message") if isinstance(d.get("message"), dict) else {}
    content = msg.get("content")
    if kind == "user" and not d.get("isMeta"):
        texts = [content] if isinstance(content, str) else [b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]
        return {**out, "text": "\n".join(t for t in texts if _spoken(t)), "who": "you"}
    if kind == "assistant":
        return {**out, "text": "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"),
                "who": "agent"}
    return out


def _codex_line(raw: bytes) -> dict | None:
    if b'"session_meta"' not in raw and not (b'"response_item"' in raw and b'"message"' in raw):
        return None
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
    out = {"at": _epoch(d.get("timestamp"))}
    if d.get("type") == "session_meta":
        return {**out, "cwd": p.get("cwd")}
    if p.get("type") == "message" and p.get("role") in ("user", "assistant"):
        text = "\n".join(c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict) and _spoken(c.get("text", "")))
        return {**out, "text": text, "who": "you" if p["role"] == "user" else "agent"}
    return out


class Index:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        with self.lock:
            self.db.executescript(
                "create virtual table if not exists docs using fts5(text, kind unindexed, project unindexed, source unindexed,"
                " title unindexed, at unindexed, tokenize='porter unicode61');"
                "create table if not exists files (path text primary key, offset integer, mtime real, project text, title text);")

    def _file(self, path: str) -> tuple:
        return self.db.execute("select offset, mtime, project, title from files where path = ?", (path,)).fetchone() or (0, 0, None, None)

    def _put(self, path: str, offset: int, mtime: float, project, title) -> None:
        self.db.execute("insert into files values (?, ?, ?, ?, ?) on conflict(path) do update set offset = excluded.offset,"
                        " mtime = excluded.mtime, project = excluded.project, title = excluded.title", (path, offset, mtime, project, title))

    def _add(self, text: str, kind: str, project, source: str, title, at) -> int:
        rows = [(c, kind, project or "", source, title or "", at or 0) for c in _chunks(text)]
        self.db.executemany("insert into docs (text, kind, project, source, title, at) values (?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    def refresh(self, budget: float = 2.0) -> int:
        """Index what's new; stop after about `budget` seconds (the rest waits for next time). Returns passages added."""
        until = time.time() + budget
        with self.lock:
            added = self._notes() + self._chats()
            self.db.commit()
        if settings()["sessions"]:
            for path, tool in self._session_files():
                if time.time() > until:
                    break
                added += self._session(path, tool, until)
        return added

    def _notes(self) -> int:
        current = notes()
        digest = hashlib.sha1(json.dumps(current, sort_keys=True).encode()).hexdigest()
        if self._file("notes")[3] == digest:
            return 0
        self.db.execute("delete from docs where kind = 'note'")
        n = sum(self._add(f"[{x['id']}] {x['text']}", "note", "", "notes", x["id"], x.get("at")) for x in current)
        self._put("notes", 0, time.time(), "", digest)
        return n

    def _chats(self) -> int:
        folder, n = spool.home() / "chats", 0
        for f in folder.glob("*.json") if folder.is_dir() else []:
            mtime = f.stat().st_mtime
            if self._file(str(f))[1] == mtime:
                continue
            try:
                chat = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            self.db.execute("delete from docs where source = ?", (str(f),))
            for v in chat.get("view") or []:
                n += self._add(f"You: {v.get('user', '')}\nAgent: {v.get('answer', '')}", "chat", "", str(f), chat.get("title"),
                               chat.get("updated"))
            self._put(str(f), 0, mtime, "", chat.get("title"))
        return n

    def _session_files(self) -> list[tuple[Path, str]]:
        found = []
        if claude_root().is_dir():
            found += [(p, "claude_code") for p in claude_root().glob("*/*.jsonl")]
        if codex_root().is_dir():
            found += [(p, "codex") for p in codex_root().glob("**/rollout-*.jsonl")]
        stamped = []
        for p, tool in found:
            try:
                stamped.append((p.stat().st_mtime, p, tool))
            except OSError:
                continue
        return [(p, tool) for _, p, tool in sorted(stamped, key=lambda x: -x[0])]  # newest first

    def _session(self, path: Path, tool: str, until: float) -> int:
        """Index a session file from where it was left, one block per lock, so a search never waits long."""
        with self.lock:
            offset, _, project, title = self._file(str(path))
        size, n = path.stat().st_size, 0
        parse = _claude_line if tool == "claude_code" else _codex_line
        with open(path, "rb") as f:
            while offset < size and time.time() < until:
                f.seek(offset)
                data = f.read(min(READ_BLOCK, size - offset))
                end = data.rfind(b"\n") + 1
                if not end:
                    if len(data) < READ_BLOCK:
                        break  # the last line is still being written
                    while not end and data:  # one line bigger than a block: tool output, never indexed; skip it
                        offset += len(data)
                        data = f.read(READ_BLOCK)
                        end = data.find(b"\n") + 1
                    offset += end
                    continue
                with self.lock:
                    for raw in data[:end].splitlines():
                        got = parse(raw)
                        if not got:
                            continue
                        if got.get("cwd") and not project:
                            project = Path(got["cwd"].replace("\\", "/")).name
                        if got.get("title"):
                            title = got["title"]
                        if got.get("text"):
                            who = "You" if got.get("who") == "you" else "Agent"
                            n += self._add(f"{who}: {got['text']}", tool, project, str(path), title, got.get("at") or path.stat().st_mtime)
                    offset += end
                    self._put(str(path), offset, path.stat().st_mtime, project, title)
                    self.db.commit()
        return n

    def search(self, query: str, where: str = "everywhere", project: str = "", k: int = 8) -> list[dict]:
        terms = [w for w in re.findall(r"[a-z0-9_]{2,}", query.lower()) if w not in STOP][:12]
        if not terms:
            return []
        sql = ("select kind, project, title, at, snippet(docs, 0, '', '', ' … ', 48), bm25(docs) from docs where docs match ?")
        params: list = [" OR ".join(f'"{w}"' for w in terms)]
        if where in KINDS:
            sql += f" and kind in ({','.join('?' * len(KINDS[where]))})"
            params += KINDS[where]
        if project:
            sql += " and lower(project) = lower(?)"
            params.append(project)
        with self.lock:
            rows = self.db.execute(sql + " order by bm25(docs) limit ?", (*params, k * 4)).fetchall()
        now = time.time()
        ranked = sorted(rows, key=lambda r: r[5] * (1.3 if now - float(r[3] or 0) < 14 * 86400 else 1.0))  # recent first among equals
        return [{"kind": r[0], "project": r[1], "title": r[2], "at": float(r[3] or 0), "text": redact.redact(r[4])} for r in ranked[:k]]

    def stats(self) -> dict:
        with self.lock:
            kinds = dict(self.db.execute("select kind, count(*) from docs group by kind").fetchall())
            sources = self.db.execute("select count(distinct source), count(distinct project) from docs where kind in"
                                      " ('claude_code', 'codex')").fetchone()
            done = {p: o for p, o in self.db.execute("select path, offset from files")}
        waiting = 0
        if settings()["sessions"]:
            for p, _ in self._session_files():
                try:
                    waiting += max(0, p.stat().st_size - done.get(str(p), 0))
                except OSError:
                    pass
        return {"notes": kinds.get("note", 0), "chats": kinds.get("chat", 0),
                "session_passages": kinds.get("claude_code", 0) + kinds.get("codex", 0), "sessions": sources[0],
                "projects": sources[1], "waiting_bytes": waiting}


_index: Index | None = None
_index_lock = threading.Lock()


def index() -> Index:
    global _index
    with _index_lock:
        path = _dir() / "index.db"
        if _index is None or _index.path != path:
            _index = Index(path)
        return _index


def start_indexer() -> None:
    """Keep the index current in the background while the app is open: a little at a time, newest sessions first."""
    def loop() -> None:
        time.sleep(10)
        while True:
            try:
                busy = index().refresh(budget=20) > 0
            except Exception:  # noqa: BLE001 - try again next round
                busy = False
            time.sleep(30 if busy else 300)
    threading.Thread(target=loop, daemon=True, name="memory-index").start()


def describe(hit: dict) -> str:
    when = time.strftime("%Y-%m-%d", time.localtime(hit["at"])) if hit["at"] else ""
    where = {"note": "note", "chat": "chat", "claude_code": "Claude Code", "codex": "Codex"}.get(hit["kind"], hit["kind"])
    bits = [where, hit["project"], f'"{hit["title"]}"' if hit["title"] and hit["kind"] != "note" else "", when]
    return f"[{' · '.join(b for b in bits if b)}] {hit['text']}"
