"""Connectors: MCP servers the agents can use, like Claude Desktop's. A connector is a local command (stdio) or an HTTP
URL (streamable HTTP) with optional headers. Kept in ~/.teamloop/connectors.json; secrets in it (tokens) never leave
this laptop except to the server they belong to.

The app keeps one live session per connector on a background asyncio loop and calls tools from the agent loop's
thread. A tool marked readOnlyHint by its server counts as a read; any other tool is a change and follows the mode."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import re
import secrets
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass

from teamloop import spool

PRESETS = [
    {"preset": "github", "name": "GitHub", "kind": "http", "url": "https://api.githubcopilot.com/mcp/",
     "about": "Issues, pull requests, code search, Actions. Needs a GitHub personal access token.",
     "fields": [{"key": "token", "label": "Personal access token", "secret": True, "header": "Authorization", "prefix": "Bearer "}]},
    {"preset": "context7", "name": "Context7", "kind": "http", "url": "https://mcp.context7.com/mcp",
     "about": "Up-to-date docs and examples for thousands of libraries. No account needed.", "fields": []},
    {"preset": "filesystem", "name": "Filesystem", "kind": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-filesystem"],
     "about": "Read and write files in folders you choose. Needs Node.js.",
     "fields": [{"key": "folder", "label": "Folder", "arg": True}]},
    {"preset": "memory", "name": "Memory", "kind": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"],
     "about": "A small knowledge graph the agent keeps between chats. Needs Node.js.", "fields": []},
]
NAME_OK = re.compile(r"[^a-zA-Z0-9_-]+")


@dataclass
class Tool:
    connector: str
    name: str        # the server's own name
    full: str        # what the model calls: mcp__<connector>__<name>
    description: str
    schema: dict
    read_only: bool


def _path():
    return spool.home() / "connectors.json"


def load() -> list[dict]:
    try:
        return [c for c in json.loads(_path().read_text(encoding="utf-8")) if isinstance(c, dict) and c.get("id")]
    except (OSError, ValueError):
        return []


def _write(items: list[dict]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def public(c: dict) -> dict:
    """What the UI may show: secrets masked."""
    out = {k: v for k, v in c.items() if k not in ("headers", "env")}
    out["headers"] = {k: ("••••" if v else "") for k, v in (c.get("headers") or {}).items()}
    out["env"] = {k: "••••" for k in (c.get("env") or {})}
    return out


def from_preset(preset: str, values: dict) -> dict:
    p = next((x for x in PRESETS if x["preset"] == preset), None)
    if not p:
        raise KeyError(preset)
    c = {"id": f"{preset}-{secrets.token_hex(2)}", "name": p["name"], "kind": p["kind"], "preset": preset, "enabled": True}
    if p["kind"] == "http":
        c.update(url=p["url"], headers={})
    else:
        c.update(command=p["command"], args=list(p["args"]), env={})
    for f in p["fields"]:
        value = str(values.get(f["key"]) or "").strip()
        if not value:
            raise ValueError(f"{f['label']} is needed")
        if f.get("header"):
            c["headers"][f["header"]] = f.get("prefix", "") + value
        if f.get("arg"):
            c["args"].append(value)
    return c


def custom(fields: dict) -> dict:
    name = " ".join(str(fields.get("name") or "").split())[:40]
    if not name:
        raise ValueError("Give the connector a name")
    c = {"id": f"{NAME_OK.sub('-', name.lower()).strip('-')[:20] or 'mcp'}-{secrets.token_hex(2)}", "name": name, "enabled": True}
    if fields.get("url"):
        url = str(fields["url"]).strip()
        if not url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("Use an https:// URL (or http://localhost for a server on this laptop)")
        c.update(kind="http", url=url, headers={str(k): str(v) for k, v in (fields.get("headers") or {}).items() if k})
    elif fields.get("command"):
        c.update(kind="stdio", command=str(fields["command"]).strip(), args=[str(a) for a in fields.get("args") or []],
                 env={str(k): str(v) for k, v in (fields.get("env") or {}).items() if k})
    else:
        raise ValueError("A connector needs a command or a URL")
    return c


class Manager:
    """Live MCP sessions on one asyncio loop in a daemon thread. Thread-safe entry points: tools(), call(), drop(), test().

    Each session lives in its own task, which opens it and later closes it: the MCP client's anyio scopes must be exited
    by the task that entered them."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True, name="mcp").start()
        self.live: dict[str, tuple[asyncio.Event, asyncio.Task, object, list[Tool]]] = {}  # id -> (stop, task, session, tools)
        self.errors: dict[str, str] = {}
        self.lock = threading.Lock()

    def _run(self, coro, timeout: float):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return fut.result(timeout)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            raise TimeoutError(f"no answer in {timeout:.0f} s") from None

    async def _hold(self, c: dict, ready: asyncio.Future, stop: asyncio.Event) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamablehttp_client

        try:
            async with AsyncExitStack() as stack:
                if c["kind"] == "stdio":
                    params = StdioServerParameters(command=c["command"], args=c.get("args") or [], env={**os.environ, **(c.get("env") or {})})
                    read, write = await stack.enter_async_context(stdio_client(params))
                else:
                    read, write, _ = await stack.enter_async_context(streamablehttp_client(c["url"], headers=c.get("headers") or None))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                listed = (await session.list_tools()).tools
                ready.set_result((session, listed))
                await stop.wait()
        except BaseException as e:  # noqa: BLE001 - reported to whoever is waiting to connect
            if not ready.done():
                ready.set_exception(e if isinstance(e, Exception) else RuntimeError("cancelled"))

    async def _connect(self, c: dict):
        ready, stop = self.loop.create_future(), asyncio.Event()
        task = self.loop.create_task(self._hold(c, ready, stop))
        try:
            session, listed = await ready
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        cid = NAME_OK.sub("_", c["id"])[:24]
        tools = []
        for t in listed:
            ann = getattr(t, "annotations", None)
            tools.append(Tool(c["id"], t.name, f"mcp__{cid}__{NAME_OK.sub('_', t.name)}"[:64], (t.description or "")[:1000],
                              t.inputSchema or {"type": "object", "properties": {}}, bool(ann and getattr(ann, "readOnlyHint", False))))
        return stop, task, session, tools

    async def _close(self, stop: asyncio.Event, task: asyncio.Task) -> None:
        stop.set()
        await asyncio.gather(task, return_exceptions=True)

    def tools(self, connector_ids: list[str], timeout: float = 30) -> list[Tool]:
        """Tools of these connectors, connecting the ones not live yet. A connector that fails is skipped; its error
        is in self.errors."""
        configs = {c["id"]: c for c in load() if c.get("enabled", True)}
        out = []
        for cid in connector_ids:
            c = configs.get(cid)
            if not c:
                continue
            with self.lock:
                if cid not in self.live:
                    try:
                        self.live[cid] = self._run(self._connect(c), timeout)
                        self.errors.pop(cid, None)
                    except Exception as e:  # noqa: BLE001 - shown on the Connectors page
                        self.errors[cid] = f"{type(e).__name__}: {e}"[:300]
                        continue
            out.extend(self.live[cid][3])
        return out

    def call(self, tool: Tool, args: dict, timeout: float = 120) -> tuple[str, bool]:
        """Run one tool. Returns (text, is_error)."""
        from mcp.shared.exceptions import McpError

        live = self.live.get(tool.connector)
        if not live:
            return "The connector disconnected. It reconnects on the next message.", True
        try:
            result = self._run(live[2].call_tool(tool.name, args), timeout)
        except Exception as e:
            if not isinstance(e, McpError):  # the server answered with an error: the connection is fine
                self.drop(tool.connector)    # otherwise it's dead: reconnect on the next message
            raise
        parts = []
        for item in result.content or []:
            text = getattr(item, "text", None)
            parts.append(text if text is not None else f"[{getattr(item, 'type', 'content')} omitted]")
        return "\n".join(parts) or "(no output)", bool(getattr(result, "isError", False))

    def drop(self, cid: str) -> None:
        with self.lock:
            live = self.live.pop(cid, None)
        if live:
            try:
                self._run(self._close(live[0], live[1]), 10)
            except Exception:  # noqa: BLE001 - best effort
                pass

    def test(self, c: dict, timeout: float = 30) -> list[str]:
        """Connect once, list the tools, disconnect: the Connectors page's "Test"."""
        stop, task, _, tools = self._run(self._connect(c), timeout)
        self._run(self._close(stop, task), 10)
        return [t.name for t in tools]


def save_all(items: list[dict]) -> None:
    _write(items)
