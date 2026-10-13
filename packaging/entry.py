"""teamloop.exe entry point. Hooks run on every tool call, so they skip the CLI and its argument parsing."""

import sys

if len(sys.argv) == 3 and sys.argv[1] == "hook":
    from teamloop.hook import main as hook_main

    raise SystemExit(hook_main(sys.argv[2]))

from teamloop.cli import main  # noqa: E402

raise SystemExit(main())
