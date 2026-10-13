"""Vercel entry point: one Python serverless function (docs/deploy.md, docs/cloud.md).

With DATABASE_URL set (Supabase Postgres), this is the cloud hub: GitHub or email sign-in, teams, invite links,
`teamloop login`. Without it, the self-hosted hub serves the public demo from /tmp SQLite, which is per instance
and re-seeds on every cold start.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "hub"), str(ROOT / "agent_s"), str(ROOT / "cloud")]

if os.environ.get("DATABASE_URL"):
    from cloud.app import create  # noqa: E402

    app = create()
else:
    os.environ.setdefault("HUB_DB", "/tmp/teamloop-hub.db")
    os.environ.setdefault("HUB_DEMO_ROOM", "demo")
    from hub.app import app_from_env  # noqa: E402

    app = app_from_env()
