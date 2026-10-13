"""`teamloop` with no command, which is what a double-click or the Start-menu shortcut runs: open the board.

1. A hub is already running here: open its board.
2. This machine is a lead (it has hub settings): start the hub, which opens the board.
3. This machine is a teammate (logged in): open the team's board.
4. Nothing set up yet: say how to start, and keep the window open so the words can be read.
"""

from __future__ import annotations

import json
import urllib.request
import webbrowser

from teamloop import spool

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
    if _hub_running():
        print(f"Your TeamLoop hub is running. Opening the board: {LOCAL}")
        webbrowser.open(LOCAL)
        return 0
    if (spool.home() / "hub" / "settings.json").is_file():
        from teamloop import hubcmd

        return hubcmd.run()
    cfg_path = spool.home() / "config.json"
    if cfg_path.is_file():
        url = json.loads(cfg_path.read_text(encoding="utf-8")).get("url", "")
        print(f"Opening your team's board: {url}")
        webbrowser.open(url)
        _pause()
        return 0
    print("TeamLoop: live progress from every teammate's AI coding session, on one board.\n")
    print("  Lead:      teamloop hub                    starts your team's board on this machine")
    print("  Teammate:  teamloop login <invite>         then, in your repo:  teamloop init")
    print("  Help:      teamloop --help   |   teamloop doctor")
    _pause()
    return 0
