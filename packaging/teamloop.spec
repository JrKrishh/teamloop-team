# PyInstaller spec: one folder, two programs sharing it.
#   SuperAgents.exe  the app window (no console): Agent S, the board, sign-in, this laptop's setup
#   teamloop.exe     hooks, the MCP server and the CLI (console), plus the self-hosted hub (`teamloop hub`)
# Build:  pyinstaller packaging/teamloop.spec --distpath dist --workpath build/pyi --noconfirm
# One folder, not one file: a one-file exe unpacks itself on every start, and hooks run on every tool call.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "brand" / "icon.ico")
datas = [
    (str(ROOT / "hub" / "hub" / "static"), "hub/static"),
    (str(ROOT / "hub" / "hub" / "demo"), "hub/demo"),
    (str(ROOT / "app" / "superagents" / "ui"), "superagents/ui"),
    (str(ROOT / "LICENSE"), "."),
]
hidden = (collect_submodules("uvicorn") + collect_submodules("anyio")
          + collect_submodules("mcp", filter=lambda m: not m.startswith("mcp.cli"))  # mcp.cli needs typer and exits
          + collect_submodules("teamloop") + collect_submodules("hub") + collect_submodules("agent_s")
          + collect_submodules("superagents"))

a = Analysis([str(ROOT / "packaging" / "entry.py")],
             pathex=[str(ROOT / "connector"), str(ROOT / "hub"), str(ROOT / "agent_s"), str(ROOT / "app")],
             datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "numpy", "PIL", "pytest", "IPython", "openai", "PyQt5", "PyQt6", "PySide6", "gi"])
pyz = PYZ(a.pure)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="teamloop", console=True, upx=False, icon=ICON)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SuperAgents", console=False, upx=False, icon=ICON)
coll = COLLECT(cli, gui, a.binaries, a.datas, name="teamloop", upx=False)
