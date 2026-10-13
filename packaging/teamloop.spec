# PyInstaller spec for teamloop.exe: the connector (hooks, MCP, CLI) and the hub (board, Agent S) in one program.
# Build:  pyinstaller packaging/teamloop.spec --distpath dist --workpath build/pyi --noconfirm
# One folder, not one file: a one-file exe unpacks itself on every start, and hooks run on every tool call.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
datas = [
    (str(ROOT / "hub" / "hub" / "static"), "hub/static"),
    (str(ROOT / "hub" / "hub" / "demo"), "hub/demo"),
    (str(ROOT / "LICENSE"), "."),
]
hidden = (collect_submodules("uvicorn") + collect_submodules("anyio")
          + collect_submodules("mcp", filter=lambda m: not m.startswith("mcp.cli"))  # mcp.cli needs typer and exits
          + collect_submodules("teamloop") + collect_submodules("hub") + collect_submodules("agent_s"))

a = Analysis([str(ROOT / "packaging" / "entry.py")], pathex=[str(ROOT / "connector"), str(ROOT / "hub"), str(ROOT / "agent_s")],
             datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "numpy", "PIL", "pytest", "IPython", "openai"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="teamloop", console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="teamloop", upx=False)
