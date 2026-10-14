"""TeamLoop in its own window: Edge or Chrome in app mode (no tabs, no address bar), with the default browser as
the fallback. A real browser rather than an embedded webview: Edge is on every Windows machine, and the person's
existing GitHub sign-in carries over, so signing in to TeamLoop is one click."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

CLOUD = os.environ.get("TEAMLOOP_HUB", "https://teamloop.vercel.app")


def _browsers() -> list[str]:
    found = [shutil.which(n) for n in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser")]
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if base:
                found += [str(Path(base) / "Microsoft/Edge/Application/msedge.exe"), str(Path(base) / "Google/Chrome/Application/chrome.exe")]
    elif sys.platform == "darwin":
        found += ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return [b for b in found if b and Path(b).is_file()]


def open_app(url: str) -> None:
    for exe in _browsers():
        try:
            subprocess.Popen([exe, f"--app={url}", "--window-size=1280,860"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue
    webbrowser.open(url)


def super_agents() -> bool:
    """Start the Super Agents app without waiting for it: SuperAgents.exe next to this exe, or the superagents
    package when installed with pip. False when neither is here."""
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    exe = Path(sys.executable).with_name("SuperAgents.exe")
    if getattr(sys, "frozen", False) and exe.is_file():
        cmd = [str(exe)]
    else:
        try:
            import superagents  # noqa: F401
        except ImportError:
            return False
        cmd = [sys.executable, "-m", "superagents"]
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, close_fds=True)
    return True


def run(url: str | None = None) -> int:
    """`teamloop app`: the Super Agents app; without it, the board in a browser window."""
    if not url and super_agents():
        print("Opening Super Agents.")
        return 0
    from teamloop import send

    cfg = send.config() or {}
    url = url or (cfg.get("url") if cfg.get("mode") == "cloud" else None) or CLOUD
    print(f"Opening TeamLoop: {url}")
    open_app(url)
    return 0
