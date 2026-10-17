"""Shared fakes: a ChatGPT stand-in and an in-memory store. No network."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.chatgpt_backend import Reply  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

ADMIN_USER = "admin"
ADMIN_PASS = "correct-horse-battery"
API_KEY = "k3y-for-scripts-0123456789abcdef"
TOKEN = "eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0.sampleTOKENvalue_xyz987"


class MemoryStore:
    def __init__(self) -> None:
        self.items: dict[str, bytes] = {}

    async def read(self, name):
        return self.items.get(name)

    async def write(self, name, data, content_type="application/json"):
        self.items[name] = data

    async def delete(self, name):
        self.items.pop(name, None)


class FakeChatGPT:
    """Records conversations. A send with `delay` is cut off by the caller; the reply stays unfinished until finish_all()."""

    def __init__(self) -> None:
        self.conversations: dict[str, list[dict]] = {}
        self.sent_conversation_ids: list[str | None] = []
        self.delay = 0.0
        self.error: Exception | None = None
        self.latest_calls = 0
        self.latest_error: Exception | None = None
        self.never_names_chat = False
        self._n = 0

    async def send(self, token, message, model, conversation_id, on_conversation):
        if self.error is not None:
            raise self.error
        self.sent_conversation_ids.append(conversation_id)
        cid = conversation_id or f"conv-{len(self.conversations) + 1}"
        self.conversations.setdefault(cid, [])
        if not self.never_names_chat:
            on_conversation(cid)
        self._n += 1
        entry = {"id": f"m{self._n}", "text": f"Answer to: {message}", "finished": False}
        self.conversations[cid].append(entry)
        if self.delay:
            await asyncio.sleep(self.delay)
        entry["finished"] = True
        return Reply(id=entry["id"], text=entry["text"], finished=True)

    async def latest_reply(self, token, conversation_id):
        self.latest_calls += 1
        if self.latest_error is not None:
            raise self.latest_error
        entries = self.conversations.get(conversation_id) or []
        if not entries:
            return None
        last = entries[-1]
        return Reply(id=last["id"], text=last["text"], finished=last["finished"])

    def finish_all(self):
        for entries in self.conversations.values():
            for entry in entries:
                entry["finished"] = True


@pytest.fixture
def settings(tmp_path):
    return Settings(
        admin_username=ADMIN_USER,
        admin_password=ADMIN_PASS,
        secret_key="s" * 48,
        cookie_secure=False,
        data_dir=tmp_path,
        api_key=API_KEY,
    )


@pytest.fixture
def backend():
    return FakeChatGPT()


@pytest.fixture
def client(settings, backend, monkeypatch):
    """A logged-in admin with a saved token and a fake ChatGPT behind the app."""
    import app.chat_service as chat_service

    monkeypatch.setattr(chat_service, "CHECK_SECONDS", 0.0)
    app = create_app(settings, backend=backend, store=MemoryStore())
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}).status_code == 200
        assert c.post("/api/session/token", json={"token": TOKEN}).status_code == 200
        yield c


def bearer(key: str = API_KEY) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}
