"""Chats: quick replies, pending replies, follow-ups, checks and give-up rules."""

from __future__ import annotations

import pytest

import app.chat_service as chat_service
from tests.conftest import TOKEN, bearer


def test_a_quick_reply_comes_back_in_the_send(client):
    resp = client.post("/api/chat/send", json={"message": "capital of France?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "answered"
    assert [m["role"] for m in body["messages"]] == ["user", "model"]
    assert body["messages"][1]["text"] == "Answer to: capital of France?"


def test_a_follow_up_continues_the_same_conversation(client, backend):
    chat_id = client.post("/api/chat/send", json={"message": "one"}).json()["chat"]["id"]
    resp = client.post("/api/chat/send", json={"chat_id": chat_id, "message": "two"})
    assert resp.status_code == 200
    assert resp.json()["chat"]["id"] == chat_id
    assert backend.sent_conversation_ids == [None, "conv-1"]


def test_a_slow_reply_returns_the_chat_id_as_waiting_then_the_reply(client, backend, monkeypatch):
    monkeypatch.setattr(chat_service, "SEND_WAIT_SECONDS", 0.05)
    backend.delay = 1.0
    resp = client.post("/api/chat/send", json={"message": "think hard"})
    assert resp.status_code == 202
    chat_id = resp.json()["chat"]["id"]
    assert resp.json()["status"] == "waiting"

    assert client.get(f"/api/chat/{chat_id}").json()["status"] == "waiting"
    backend.finish_all()
    done = client.get(f"/api/chat/{chat_id}").json()
    assert done["status"] == "answered"
    assert done["messages"][-1]["text"] == "Answer to: think hard"


def test_a_follow_up_while_waiting_is_a_409(client, backend, monkeypatch):
    monkeypatch.setattr(chat_service, "SEND_WAIT_SECONDS", 0.05)
    backend.delay = 1.0
    chat_id = client.post("/api/chat/send", json={"message": "first"}).json()["chat"]["id"]
    resp = client.post("/api/chat/send", json={"chat_id": chat_id, "message": "second"})
    assert resp.status_code == 409
    assert "still being answered" in resp.json()["detail"]


def test_checks_of_a_pending_reply_are_spaced_out(client, backend, monkeypatch):
    monkeypatch.setattr(chat_service, "SEND_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(chat_service, "CHECK_SECONDS", 60.0)
    backend.delay = 1.0
    chat_id = client.post("/api/chat/send", json={"message": "slow"}).json()["chat"]["id"]
    before = backend.latest_calls
    for _ in range(5):
        assert client.get(f"/api/chat/{chat_id}").json()["status"] == "waiting"
    assert backend.latest_calls - before == 1


def test_an_older_reply_is_not_taken_for_the_new_one(client, backend, monkeypatch):
    chat_id = client.post("/api/chat/send", json={"message": "one"}).json()["chat"]["id"]
    monkeypatch.setattr(chat_service, "SEND_WAIT_SECONDS", 0.05)
    backend.delay = 1.0
    client.post("/api/chat/send", json={"chat_id": chat_id, "message": "two"})
    assert client.get(f"/api/chat/{chat_id}").json()["status"] == "waiting"  # m1 is still the newest reply
    backend.finish_all()
    done = client.get(f"/api/chat/{chat_id}").json()
    assert done["status"] == "answered"
    assert done["messages"][-1]["text"] == "Answer to: two"


def test_no_conversation_id_before_the_wait_is_failed_but_keeps_its_id(client, backend, monkeypatch):
    monkeypatch.setattr(chat_service, "SEND_WAIT_SECONDS", 0.05)
    backend.delay = 1.0
    backend.never_names_chat = True
    resp = client.post("/api/chat/send", json={"message": "stuck"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"
    chat_id = resp.json()["chat"]["id"]
    assert "Send it again" in client.get(f"/api/chat/{chat_id}").json()["pending"]["error"]


def test_a_reply_never_written_is_given_up_after_the_wait(client, backend, monkeypatch):
    monkeypatch.setattr(chat_service, "SEND_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(chat_service, "REPLY_WAIT_SECONDS", 0.0)
    backend.delay = 1.0
    chat_id = client.post("/api/chat/send", json={"message": "lost"}).json()["chat"]["id"]
    resp = client.get(f"/api/chat/{chat_id}").json()
    assert resp["status"] == "failed"
    assert "did not reply within 30 minutes" in resp["pending"]["error"]


def test_a_failed_check_is_recorded_and_the_chat_stays_waiting(client, backend, monkeypatch):
    monkeypatch.setattr(chat_service, "SEND_WAIT_SECONDS", 0.05)
    backend.delay = 1.0
    chat_id = client.post("/api/chat/send", json={"message": "slow"}).json()["chat"]["id"]
    backend.latest_error = OSError("network down")
    resp = client.get(f"/api/chat/{chat_id}").json()
    assert resp["status"] == "waiting"
    assert resp["pending"]["check_failures"] == 1
    assert "network down" in resp["pending"]["last_check_error"]


def test_sending_without_a_saved_token_is_a_409(settings, backend):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import ADMIN_PASS, ADMIN_USER, MemoryStore

    with TestClient(create_app(settings, backend=backend, store=MemoryStore())) as c:
        c.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
        resp = c.post("/api/chat/send", json={"message": "hi"})
    assert resp.status_code == 409
    assert "Save a session cookie first" in resp.json()["detail"]


def test_list_and_delete_chats(client):
    chat_id = client.post("/api/chat/send", json={"message": "to delete"}).json()["chat"]["id"]
    assert client.get("/api/chat").json()["chats"][0]["id"] == chat_id
    assert client.delete(f"/api/chat/{chat_id}").json() == {"ok": True}
    assert client.get("/api/chat").json()["chats"] == []
    assert client.get(f"/api/chat/{chat_id}").status_code == 404


def test_bad_and_empty_messages_are_refused(client):
    assert client.post("/api/chat/send", json={"message": ""}).status_code == 422
    assert client.post("/api/chat/send", json={"message": "x" * 8001}).status_code == 422
    assert client.get("/api/chat/not-an-id").status_code == 422


def test_the_token_is_masked_and_never_returned_whole(client):
    status = client.get("/api/session").json()["token"]
    assert status["saved"] is True
    assert TOKEN not in str(status)
    assert status["masked"].startswith(TOKEN[:4])


def test_a_cookie_header_with_the_token_name_is_accepted(client):
    resp = client.post("/api/session/token", json={"token": f"__Secure-next-auth.session-token={TOKEN}; other=1"})
    assert resp.status_code == 200
    assert client.get("/api/session").json()["token"]["saved"] is True


def test_a_non_token_is_refused(client):
    resp = client.post("/api/session/token", json={"token": "short"})
    assert resp.status_code == 422
