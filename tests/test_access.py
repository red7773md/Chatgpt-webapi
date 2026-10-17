"""Who may call what: the API key, browser login, cookie-free routes, and MCP."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import ADMIN_PASS, ADMIN_USER, API_KEY, MemoryStore, bearer


def test_the_key_opens_the_chat_routes_without_a_login(settings, backend):
    with TestClient(create_app(settings, backend=backend, store=MemoryStore())) as c:
        assert c.get("/api/chat", headers=bearer()).status_code == 200
        assert c.get(f"/api/chat?key={API_KEY}").status_code == 200
        assert c.get("/api/chat", headers={"X-API-Key": API_KEY}).status_code == 200


def test_a_wrong_or_missing_key_is_refused(settings, backend):
    with TestClient(create_app(settings, backend=backend, store=MemoryStore())) as c:
        assert c.get("/api/chat").status_code == 401
        assert c.get("/api/chat", headers=bearer("wrong-key-000000000000000000")).status_code == 401


def test_the_key_cannot_reach_the_token_routes(settings, backend):
    with TestClient(create_app(settings, backend=backend, store=MemoryStore())) as c:
        assert c.get("/api/session", headers=bearer()).status_code == 401
        assert c.post("/api/session/token", headers=bearer(), json={"token": "x" * 40}).status_code == 401
        assert c.delete("/api/session/token", headers=bearer()).status_code == 401


def test_the_key_is_ignored_when_none_is_configured(settings, backend):
    settings_without = settings.__class__(**{**settings.__dict__, "api_key": None})
    with TestClient(create_app(settings_without, backend=backend, store=MemoryStore())) as c:
        assert c.get("/api/chat", headers=bearer()).status_code == 401


def test_repeated_wrong_keys_lock_the_client_out(settings, backend):
    with TestClient(create_app(settings, backend=backend, store=MemoryStore())) as c:
        for _ in range(5):
            c.get("/api/chat", headers=bearer("wrong-key-000000000000000000"))
        locked = c.get("/api/chat", headers=bearer())
        assert locked.status_code == 429
        assert "Retry-After" in locked.headers


def test_a_browser_login_still_opens_the_chat_routes(client):
    assert client.get("/api/chat").status_code == 200


def test_unknown_paths_are_404_not_the_mcp_endpoint(client):
    assert client.get("/api/nothing-here", headers=bearer()).status_code == 404


# ----- MCP -----------------------------------------------------------------

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(client, method, params, req_id=1, key=API_KEY):
    headers = {**MCP_HEADERS, **bearer(key)}
    return client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})


def test_mcp_needs_the_api_key(client):
    resp = client.post("/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert resp.status_code == 401


def test_mcp_lists_the_chatgpt_tools(client):
    init = rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    assert init.status_code == 200
    assert init.json()["result"]["serverInfo"]["name"] == "chatgpt-archive"
    tools = rpc(client, "tools/list", {}, req_id=2).json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert names == {"chatgpt_send", "chatgpt_get_chat", "chatgpt_list_chats", "chatgpt_delete_chat"}


def test_mcp_send_returns_the_reply_as_a_tool_result(client):
    rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    resp = rpc(client, "tools/call", {"name": "chatgpt_send", "arguments": {"message": "hello"}}, req_id=3).json()
    result = resp["result"]
    assert result.get("isError") in (False, None)
    data = result.get("structuredContent") or {}
    assert data["status"] == "answered"
    assert data["messages"][-1]["text"] == "Answer to: hello"


def test_mcp_refuses_a_send_when_no_token_is_saved(settings, backend):
    with TestClient(create_app(settings, backend=backend, store=MemoryStore())) as c:
        rpc(c, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
        resp = rpc(c, "tools/call", {"name": "chatgpt_send", "arguments": {"message": "hi"}}, req_id=4).json()
    assert resp["result"]["isError"] is True
    assert "Save a session token first" in str(resp["result"]["content"])
