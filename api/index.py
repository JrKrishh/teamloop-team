"""Vercel entry point: the hub as one Python serverless function (docs/deploy.md).

This hosts the public demo. Its SQLite file lives in /tmp, which is per instance and temporary, so the demo
room re-seeds itself on every cold start. Real teams need the persistent store (PLAN.md §6.5) before they can
use a serverless host.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "hub"), str(ROOT / "agent_s")]
os.environ.setdefault("HUB_DB", "/tmp/teamloop-hub.db")
os.environ.setdefault("HUB_DEMO_ROOM", "demo")

from hub.app import app_from_env  # noqa: E402

app = app_from_env()
