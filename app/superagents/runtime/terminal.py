"""The in-app terminal: a real shell in a pseudo-terminal (ConPTY via pywinpty on Windows, pty elsewhere), wired to
xterm.js in the window over a WebSocket. PowerShell 7 if it's installed, else Windows PowerShell; $SHELL elsewhere."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


class Pty:
    def __init__(self, cwd: Path, cols: int = 100, rows: int = 30) -> None:
        cols, rows = max(20, min(cols, 400)), max(5, min(rows, 200))
        if sys.platform == "win32":
            from winpty import PtyProcess

            shell = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
            self.p = PtyProcess.spawn([shell, "-NoLogo"], cwd=str(cwd), dimensions=(rows, cols))
        else:
            import pty
            import subprocess

            master, slave = pty.openpty()
            self.proc = subprocess.Popen([os.environ.get("SHELL", "/bin/bash")], stdin=slave, stdout=slave, stderr=slave,
                                         cwd=str(cwd), start_new_session=True, env={**os.environ, "TERM": "xterm-256color"})
            os.close(slave)
            self.fd = master
            self.resize(cols, rows)

    def read(self) -> str:
        if sys.platform == "win32":
            return self.p.read(4096)
        try:
            return os.read(self.fd, 4096).decode("utf-8", errors="replace")
        except OSError:
            return ""

    def write(self, data: str) -> None:
        if sys.platform == "win32":
            self.p.write(data)
        else:
            os.write(self.fd, data.encode())

    def resize(self, cols: int, rows: int) -> None:
        cols, rows = max(20, min(cols, 400)), max(5, min(rows, 200))
        if sys.platform == "win32":
            self.p.setwinsize(rows, cols)
        else:
            import fcntl
            import struct
            import termios

            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def alive(self) -> bool:
        return self.p.isalive() if sys.platform == "win32" else self.proc.poll() is None

    def kill(self) -> None:
        try:
            if sys.platform == "win32":
                self.p.terminate(force=True)
            else:
                self.proc.kill()
                os.close(self.fd)
        except Exception:  # noqa: BLE001 - already gone
            pass
