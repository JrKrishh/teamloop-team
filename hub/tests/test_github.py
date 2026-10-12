"""GitHub receiver with fixtures built from this repo's own PR #1 and its CI (tests/fixtures/github)."""

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub.app import create
from tests.test_team import fake_chat, member

FIX = Path(__file__).parent / "fixtures" / "github"
SECRET = "webhook-secret-for-tests"


def fixture(name):
    return (FIX / name).read_bytes()


def deliver(client, event, body, delivery="d-1", secret=SECRET):
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/v1/github", content=body, headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": event,
                                                            "X-GitHub-Delivery": delivery, "Content-Type": "application/json"})


@pytest.fixture
def hub(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("HUB_GITHUB_REPOS", "JrKrishh/teamloop-team=teamloop")
    app = create(":memory:", chat=fake_chat, start_worker=False)
    client = TestClient(app)
    return app, client, member(client, "yang")


def test_signature_is_required(hub, monkeypatch):
    _, client, _ = hub
    body = fixture("pull_request_opened.json")
    assert deliver(client, "pull_request", body, secret="wrong").status_code == 401
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET")
    assert deliver(client, "pull_request", body).status_code == 503


def test_draft_pr_attaches_but_is_not_review_yet(hub):
    _, client, yang = hub
    r = deliver(client, "pull_request", fixture("pull_request_opened.json"))
    assert r.status_code == 202 and r.json()["accepted"] == 1
    [task] = client.get("/v1/board", headers=yang).json()["tasks"]
    assert task["task"] == "T-14" and task["pr"]["number"] == 1 and task["pr"]["draft"] is True
    assert task["status"] != "review" and task["members"] == [] and task["pr"]["url"].startswith("https://github.com/")


def test_ready_pr_moves_task_to_review(hub):
    _, client, yang = hub
    payload = json.loads(fixture("pull_request_opened.json"))
    payload["action"], payload["pull_request"]["draft"] = "ready_for_review", False
    deliver(client, "pull_request", json.dumps(payload).encode())
    assert client.get("/v1/board", headers=yang).json()["tasks"][0]["status"] == "review"


def test_push_uses_the_commit_trailer_and_redelivery_is_idempotent(hub):
    _, client, yang = hub
    body = fixture("push.json")
    assert deliver(client, "push", body, "d-7").json()["accepted"] >= 1
    assert deliver(client, "push", body, "d-7").json()["accepted"] == 0
    lines = [r["line"] for r in client.get("/v1/board", headers=yang).json()["tasks"][0]["recent"]]
    assert any(line.startswith("commit ") for line in lines)


def test_unlinked_repo_and_ping_are_ignored(hub, monkeypatch):
    _, client, yang = hub
    assert deliver(client, "ping", b'{"zen": "Keep it logically awesome."}').json()["pong"] is True
    monkeypatch.setenv("HUB_GITHUB_REPOS", "someone/else=teamloop")
    assert deliver(client, "pull_request", fixture("pull_request_opened.json")).json()["accepted"] == 0
    assert client.get("/v1/board", headers=yang).json()["tasks"] == []


def test_github_is_not_a_team_member(hub):
    _, client, yang = hub
    deliver(client, "pull_request", fixture("pull_request_opened.json"))
    assert [m["name"] for m in client.get("/v1/board", headers=yang).json()["members"]] == []


def test_ci_result_shows_on_the_pr(hub):
    _, client, yang = hub
    deliver(client, "pull_request", fixture("pull_request_opened.json"), "d-1")
    assert deliver(client, "workflow_run", fixture("workflow_run_completed.json"), "d-2").json()["accepted"] == 1
    task = client.get("/v1/board", headers=yang).json()["tasks"][0]
    assert task["pr"]["checks"] == "success" and any(r["line"] == "CI ci: success" for r in task["recent"])
