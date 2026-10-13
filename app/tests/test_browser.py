"""The agent browser against a real Edge (or Chrome) and a page served on this laptop: the page as numbered elements,
acting by ref, waiting for a page that renders late, console and network errors, what each step needs from the person,
the live view's frames, and dev servers."""

import json
import socket
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from superagents.runtime import browser, devserver, loop, tools

PAGE = """<!doctype html><title>Shop</title><h1>Cart</h1>
<a href="/two.html">Go to page two</a>
<form action="/two.html"><label>Email <input name="email"></label><label>Password <input type="password" name="pw"></label>
<select name="size" aria-label="Size"><option>Small</option><option>Large</option></select><button>Sign in</button></form>
<button onclick="document.title = 'Deleted'">Delete account</button><div id="late"></div>
<script>console.error("boom: total is NaN"); fetch("/missing.json");
setTimeout(() => { document.getElementById("late").textContent = "Loaded later"; }, 400);</script>"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("site")
    (root / "index.html").write_text(PAGE)
    (root / "two.html").write_text("<!doctype html><title>Two</title><p>Second page</p>")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def host(tmp_path_factory):
    h = browser.BrowserHost(tmp_path_factory.mktemp("browser"))
    try:
        h.run(h._start, timeout=60)
    except Exception as e:  # noqa: BLE001 - no Edge or Chrome on this machine
        pytest.skip(f"no browser to drive: {e}")
    old, browser._host = browser._host, h
    yield h
    browser._host = old
    h.close()


def test_reads_the_page_as_numbered_elements_and_its_errors(site, host):
    out = browser.browser_open(None, site + "/index.html")
    assert "Page: Shop · " in out
    for want in ('link "Go to page two"', 'textbox "Email"', 'textbox "Password" [password]', 'combobox "Size" [value "Small"]',
                 'button "Sign in" (submits a form)', 'button "Delete account"'):
        assert want in out, want
    assert "Loaded later" in out  # it waited for the page to settle
    assert "Console: 1 error (last: boom: total is NaN)" in out and "Network: 1 failed" in out and "404" in out
    assert "missing.json → 404" in browser.browser_console(None)
    found = browser.browser_snapshot(None, find="sign")
    assert 'button "Sign in"' in found and "Go to page two" not in found


def test_acts_by_ref(site, host):
    page = browser.browser_open(None, site + "/index.html")
    ref = lambda label: next(line.split()[0] for line in page.splitlines() if label in line)  # noqa: E731
    page = browser.browser_type(None, ref('textbox "Email"'), "yang@example.com")
    assert 'textbox "Email" [value "yang@example.com"]' in page
    page = browser.browser_select(None, ref('combobox "Size"'), "Large")
    assert 'combobox "Size" [value "Large"]' in page
    page = browser.browser_click(None, ref('link "Go to page two"'))
    assert "Page: Two · " in page and "Second page" in page
    assert "Page: Shop · " in browser.browser_open(None, "back")
    out = browser.browser_batch(None, [{"tool": "browser_click", "args": {"ref": "ref_99"}}])
    assert out.startswith("1. browser_click failed")


def test_what_each_step_needs_from_the_person(site, host, monkeypatch, tmp_path):
    monkeypatch.setenv("TEAMLOOP_HOME", str(tmp_path / "home"))
    assert browser.kind_open({"url": site}) == "read"  # this laptop: free
    assert browser.kind_open({"url": "https://shop.example/cart"}) == "ask"
    browser.set_site("shop.example", True)
    assert browser.kind_open({"url": "https://shop.example/cart"}) == "read"  # always allowed now
    monkeypatch.setattr(browser, "_page_url", lambda: "https://shop.example/cart")
    host.refs = {"ref_1": {"name": "Delete account", "submits": False}, "ref_2": {"name": "Next", "submits": False},
                 "ref_3": {"name": "Go", "submits": True}}
    assert [browser.kind_click({"ref": r}) for r in ("ref_1", "ref_2", "ref_3")] == ["change", "read", "change"]
    assert browser.kind_type({"ref": "ref_2", "text": "x", "submit": True}) == "change"
    assert browser.kind_batch({"steps": [{"tool": "browser_click", "args": {"ref": "ref_2"}},
                                         {"tool": "browser_click", "args": {"ref": "ref_1"}}]}) == "change"
    browser.set_site("shop.example", False)
    assert browser.kind_click({"ref": "ref_2"}) == "ask"  # a site nobody allowed
    assert tools.BY_NAME["browser_eval"].kind == "ask"


def test_secrets_cards_and_other_sites_passwords_are_the_persons_to_type():
    with pytest.raises(PermissionError, match="Passwords"):
        browser.check_text("hunter2", {"password": True}, "https://shop.example/login")
    browser.check_text("test-password", {"password": True}, "http://localhost:3000/login")  # their own app, locally
    with pytest.raises(PermissionError, match="Card"):
        browser.check_text("4111111111111111", {"card": True}, "http://localhost:3000")
    with pytest.raises(PermissionError, match="secret"):
        browser.check_text("sk_live_abcdef1234567890abcd", {}, "http://localhost:3000")


def test_the_live_view_streams_frames_and_takes_input(site, host):
    browser.browser_open(None, site + "/index.html")
    host.run(host.watch, True)
    try:
        assert host.frame[:2] == b"\xff\xd8" and host.state()["viewers"] == 1  # a JPEG, straight away
        host.run(host.resize, 900, 640)
        assert host.state()["size"] == [900, 640]
        host.run(host.person, {"type": "click", "x": 5, "y": 5})  # the person's own click goes through
    finally:
        host.run(host.watch, False)
    assert host.state()["viewers"] == 0 and host.cdp is None


def test_the_live_view_and_a_first_page_starting_together_get_one_browser(site, host, tmp_path):
    import asyncio

    h = browser.BrowserHost(tmp_path / "fresh")

    async def both():
        await asyncio.gather(h.watch(True), h.person_open(site + "/two.html"))

    try:
        h.run(both, timeout=90)
        assert h.channel == host.channel and h.skipped == [] and len(h.ctx.pages) == 1
    finally:
        h.run(h.watch, False)
        h.close()


def test_dev_servers_start_from_launch_json_and_stop(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    (tmp_path / ".superagents").mkdir()
    (tmp_path / ".superagents" / "launch.json").write_text(json.dumps({"configurations": [
        {"name": "web", "command": f'"{sys.executable}" -m http.server {port} --bind 127.0.0.1', "port": port}]}))
    got = devserver.start(tmp_path, wait=30)
    try:
        assert got["url"] == f"http://localhost:{port}" and not got["already"]
        assert devserver.start(tmp_path)["already"]
    finally:
        assert devserver.stop(tmp_path) == [f"{tmp_path.name}-web"]
    with pytest.raises(ValueError, match="no dev server"):
        devserver.start(tmp_path / "nothing-here")


def test_a_turn_that_changed_ui_files_is_asked_to_check_them_in_the_browser(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMLOOP_HOME", str(tmp_path / "home"))
    (tmp_path / "web" / "src").mkdir(parents=True)
    monkeypatch.setattr(tools, "roots", lambda: {"web": tmp_path / "web"})
    steps = iter([{"content": None, "tool_calls": [{"id": "w1", "type": "function", "function": {
                      "name": "write_file", "arguments": json.dumps({"path": "web/src/App.tsx", "content": "export {}"})}}]},
                  {"content": "Done: the header is fixed.", "tool_calls": []},
                  {"content": "Checked it: no console errors.", "tool_calls": []}])
    sent = []

    def llm(messages, tools_, tier):
        sent.append(list(messages))
        return next(steps)

    class NoMcp:
        errors: dict = {}

        def tools(self, ids):
            return []

    from superagents.runtime import agents
    t = loop.Turn(chat=loop.new_chat("agent-s"), agent=agents.get("agent-s"), message="Fix the header", attachments=[],
                  mode="auto", model="auto", llm=llm, mcp=NoMcp(), person="Yang",
                  hub=lambda method, path, body=None: {"room": "Loopers", "members": [], "tasks": []})
    t.run()
    assert sent[2][-1]["content"] == loop.VERIFY_NUDGE.format(files="web/src/App.tsx")
    assert next(e["text"] for e in t.events if e["kind"] == "answer") == "Checked it: no console errors."
