"""`teamloop` with no command: open Super Agents, the app. Without the app (a bare pip install of the connector):

1. This laptop is signed in to the cloud hub: open the team's board in its own window.
2. A self-hosted hub is already running here: open its board.
3. This machine is a lead with a self-hosted hub (it has hub settings): start the hub, which opens the board.
4. This laptop joined a self-hosted hub: open that board.
5. Nothing set up yet: sign in (GitHub or email) and connect this laptop, then open the board.
"""

from __future__ import annotations

import json
import urllib.request

from teamloop import spool, window

LOCAL = "http://localhost:8799"


def _hub_running() -> bool:
    try:
        with urllib.request.urlopen(LOCAL + "/healthz", timeout=1.5) as r:
            return json.loads(r.read()).get("ok") is True
    except (OSError, ValueError):
        return False


def _pause() -> None:
    try:
        input("\nPress Enter to close.")
    except EOFError:
        pass


def run() -> int:
    if window.super_agents():  # the app does sign-in, teams and this laptop's setup
        print("Opening Super Agents.")
        return 0
    from teamloop import send

    cfg = send.config() or {}
    if cfg.get("mode") == "cloud":  # signed in to the cloud hub: that's the board, even on a machine that once self-hosted
        print(f"Opening your team's board: {cfg['url']}")
        window.open_app(cfg["url"])
        return 0
    if _hub_running():
        print(f"Your TeamLoop hub is running. Opening the board: {LOCAL}")
        window.open_app(LOCAL)
        return 0
    if (spool.home() / "hub" / "settings.json").is_file():
        from teamloop import hubcmd

        return hubcmd.run()
    cfg_path = spool.home() / "config.json"
    if cfg_path.is_file():
        url = json.loads(cfg_path.read_text(encoding="utf-8")).get("url", "")
        print(f"Opening your team's board: {url}")
        window.open_app(url)
        return 0
    from teamloop import login

    print("TeamLoop: live progress from every teammate's AI coding session, on one board.\n")
    print("First, sign in and connect this laptop to your team.")
    if login.device_login(window.CLOUD) == 0:
        print("\nThen, in each repo you work in:  teamloop init")
        window.open_app(json.loads(cfg_path.read_text(encoding="utf-8"))["url"])
    _pause()
    return 0
