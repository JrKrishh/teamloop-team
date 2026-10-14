"""A real Postgres for the cloud tests: TEST_DATABASE_URL (CI's throwaway service container) or a local pgserver.
Supabase Auth is stubbed: an access token "access-token-<name>" belongs to <name>."""

import os
import tempfile
import uuid
from pathlib import Path

import psycopg
import pytest

import cloud
from cloud import auth

SCHEMA = Path(cloud.__file__).parent / "schema.sql"
TABLES = "teams, memberships, invites, hub_sessions, devices, connector_tokens, events, snapshots, waitlist"


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("TEST_DATABASE_URL")
    srv = None
    if not url:
        pgserver = pytest.importorskip("pgserver")
        srv = pgserver.get_server(tempfile.mkdtemp(prefix="tl-pg-"), cleanup_mode="delete")
        url = srv.get_uri()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("drop schema if exists public cascade")
        conn.execute("create schema public")
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
    yield url
    if srv:
        srv.cleanup()


def person(name: str) -> auth.Person:
    return auth.Person(str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{name}.teamloop.test")), f"{name}@example.com", name)


@pytest.fixture
def env(monkeypatch, database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(f"truncate {TABLES} cascade")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setenv("HUB_SECURE_COOKIE", "0")  # the test client talks plain http
    monkeypatch.delenv("PUBLIC_URL", raising=False)

    def fake_user(access_token):
        if not access_token.startswith("access-token-"):
            raise PermissionError("Supabase refused the sign-in (401)")
        return person(access_token[13:])

    monkeypatch.setattr(auth, "supabase_user", fake_user)
    return database_url
