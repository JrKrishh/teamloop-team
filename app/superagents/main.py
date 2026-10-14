"""Start Super Agents: the local server on a free 127.0.0.1 port, then the app window (WebView2 on Windows).

`superagents --browser` opens the same UI in your browser instead, for development.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

import uvicorn

from teamloop import spool

from . import laptop, remote, server, store
from .runtime import browser, memory, superteam

CLOUD = os.environ.get("TEAMLOOP_HUB", "https://teamloop.vercel.app")
BG_DARK, BG_LIGHT = 0x00141112, 0x00E8F1F6  # COLORREF (0x00BBGGRR) of #121114 and #F6F1E8


def _quiet_children() -> None:
    """A windowed program on Windows opens a console window for every console tool it runs (git, claude, codex).
    The app runs a few of those when it connects a repo; CREATE_NO_WINDOW keeps that invisible."""
    if sys.platform != "win32":
        return
    base = subprocess.Popen

    class Quiet(base):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x08000000
            super().__init__(*args, **kwargs)

    subprocess.Popen = Quiet  # type: ignore[misc]


def _log_to_file() -> None:
    """A windowed exe has no stdout or stderr; keep what would have gone there in ~/.teamloop/app.log."""
    if sys.stdout is None or sys.stderr is None:
        spool.home().mkdir(parents=True, exist_ok=True)
        log = open(spool.home() / "app.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives with the app
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def _title_bar(window, dark: bool) -> None:
    """Match the Windows title bar to the app (dark mode on Windows 10; the exact colour on Windows 11)."""
    if sys.platform != "win32" or window is None:
        return
    try:
        import ctypes

        hwnd = window.native.Handle.ToInt64()
        flag = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(flag), ctypes.sizeof(flag))
        colour = ctypes.c_int(BG_DARK if dark else BG_LIGHT)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colour), ctypes.sizeof(colour))
    except Exception:  # noqa: BLE001 - cosmetic
        pass


def _pick_folder(state: server.State):
    def pick():
        import webview

        if state.window is None:
            return None
        chosen = state.window.create_file_dialog(webview.FileDialog.FOLDER)
        return chosen[0] if chosen else None
    return pick


def _relay(state: server.State):
    """Where the phone and this laptop meet, from the hub's /v1/config (asked once it answers)."""
    known: dict = {}

    def url():
        if "url" not in known:
            code, cfg = server.cloud(state, "GET", "/v1/config", token="")
            if code != 200:
                return None
            known["url"] = remote.relay_url(state.cloud, cfg)
        return known["url"]
    return url


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="superagents", description="Super Agents: your team's AI agents, on one page.")
    ap.add_argument("--browser", action="store_true", help="open the UI in your browser instead of the app window")
    ap.add_argument("--serve", action="store_true", help="only serve the UI and print its URL (development)")
    ap.add_argument("--hub", default=CLOUD, help="the Super Agents server (default: %(default)s)")
    args = ap.parse_args(argv)
    _log_to_file()
    _quiet_children()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    state = server.State(args.hub, port=sock.getsockname()[1])
    app = server.create(state, pick_folder=_pick_folder(state),
                        set_title_theme=lambda dark: _title_bar(state.window, dark))
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=state.port, log_level="warning", log_config=None))
    threading.Thread(target=srv.run, kwargs={"sockets": [sock]}, daemon=True).start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.025)
    url = f"http://127.0.0.1:{state.port}/#k={state.key}"
    # Super Team: run teammates' prompts in this laptop's sessions, by your rules (only while the app is open)
    state.runner = superteam.Runner(lambda method, path, body=None, query=None: server.cloud(state, method, path, body, query),
                                    team=lambda: (laptop.status().get("team") or {}).get("id") if store.load().get("session") else None,
                                    repos=lambda: laptop.status()["repos"])
    state.runner.start()
    # remote control from a phone, while remote control is on and a phone is paired (Settings → Phone)
    state.remote = remote.Remote(remote.local_api(state.port, state.key), relay=_relay(state),
                                 team=lambda: store.load().get("team") if store.load().get("session") else None)
    state.remote.start()
    memory.start_indexer()  # agents' recall over earlier chats and this laptop's coding sessions

    if args.browser or args.serve:
        print(f"Super Agents: {url}", flush=True)
        if args.browser:
            webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    import webview

    state.window = webview.create_window("Super Agents", url, width=1280, height=820, min_size=(980, 660),
                                         background_color="#121114", text_select=True)
    # the browser panel's "open in a window", for sites that won't show inside a frame
    state.open_window = lambda page: webview.create_window(f"Super Agents · {page.split('/')[2]}", page, width=1100, height=760)
    state.window.events.shown += lambda: _title_bar(state.window, True)
    webview.start(private_mode=False, storage_path=str(spool.home() / "webview"))
    srv.should_exit = True
    browser.host().close()  # the agent browser goes with the app
    return 0
