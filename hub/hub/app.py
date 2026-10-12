"""Build the hub: the ccbridge relay with TeamLoop installed on top.

    uvicorn hub.app:app_from_env --factory --port 8799
Env: HUB_DB (default teamloop-hub.db), HUB_SECRET (cookie signing; random per process if unset),
CCBRIDGE_ROOMS / CCBRIDGE_OPEN_ROOMS (as in ccbridge), AGENT_S_PROVIDER / NEBIUS_API_KEY (Agent S model),
GITHUB_WEBHOOK_SECRET / HUB_GITHUB_REPOS (owner/repo=room,...) for the GitHub receiver.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from fastapi import FastAPI

from . import github, relay, team


def create(db_path: str = ":memory:", chat: Optional[Callable] = None, open_rooms: Optional[bool] = None,
           debounce: float = 30.0, start_worker: bool = True) -> FastAPI:
    app = relay.create_app(db_path, open_rooms=open_rooms)
    team.install(app, chat=chat, debounce=debounce, start_worker=start_worker)
    github.install(app)
    return app


def app_from_env() -> FastAPI:
    return create(os.getenv("HUB_DB", "teamloop-hub.db"), debounce=float(os.getenv("HUB_DEBOUNCE", "30")))
