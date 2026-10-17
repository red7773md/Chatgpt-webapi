"""Startup and old data: a missing setting gives a readable 503, and a record from an older version does not break the page."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.entrypoint import build_entrypoint
from app.main import create_app
from tests.conftest import ADMIN_PASS, ADMIN_USER, TOKEN, MemoryStore


def test_a_missing_setting_gives_a_readable_503_on_every_route():
    with TestClient(build_entrypoint({})) as c:
        for path in ["/", "/api/auth/me", "/api/session"]:
            resp = c.get(path)
            assert resp.status_code == 503, path
            assert "ADMIN_USERNAME" in resp.json()["detail"]


def test_a_record_saved_by_the_first_version_reads_as_not_saved(settings, backend):
    store = MemoryStore()
    # The first version saved {"token", "saved_at"}. The current code reads "cookies".
    store.items["session/token.json"] = json.dumps({"token": TOKEN, "saved_at": "2026-10-16T00:00:00Z"}).encode()
    with TestClient(create_app(settings, backend=backend, store=store), base_url="https://testserver") as c:
        assert c.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}).status_code == 200
        resp = c.get("/api/session")
        assert resp.status_code == 200
        assert resp.json()["token"]["saved"] is False
        assert "older version" in resp.json()["token"]["notice"]
        assert c.post("/api/chat/send", json={"message": "hi"}).status_code == 409


def test_saving_again_replaces_an_old_record(settings, backend):
    store = MemoryStore()
    store.items["session/token.json"] = json.dumps({"token": TOKEN, "saved_at": "2026-10-16T00:00:00Z"}).encode()
    with TestClient(create_app(settings, backend=backend, store=store), base_url="https://testserver") as c:
        assert c.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}).status_code == 200
        assert c.post("/api/session/token", json={"token": TOKEN}).status_code == 200
        status = c.get("/api/session").json()["token"]
        assert status["saved"] is True
        assert "notice" not in status
