"""Entry point for both programs in the bundle: SuperAgents.exe (the app window) and teamloop.exe (hooks, MCP, CLI).
Hooks run on every tool call, so they skip everything else, argument parsing included."""

import sys
from pathlib import Path

if len(sys.argv) == 3 and sys.argv[1] == "hook":
    from teamloop.hook import main as hook_main

    raise SystemExit(hook_main(sys.argv[2]))

if Path(sys.executable).stem.lower() == "superagents":
    from superagents.main import main as app_main

    raise SystemExit(app_main(sys.argv[1:]))

from teamloop.cli import main  # noqa: E402

raise SystemExit(main())
