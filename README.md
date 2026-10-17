# ChatGPT Archive

A single-admin service over ChatGPT's web interface, with two ways in:

- **REST** at `/api/chat/...`
- **MCP** at `/mcp`, with tools `chatgpt_send`, `chatgpt_get_chat`, `chatgpt_list_chats`, `chatgpt_delete_chat`

Both use the same chat service and the same records.

**This is unofficial.** It uses ChatGPT's web endpoints with your browser session token, not the OpenAI API. That may break when ChatGPT changes, and it may breach OpenAI's terms. Use an account you can afford to lose access to.

## Status

Step 1 (skeleton): the REST routes, the MCP endpoint, the session token store, API key, and tests are in place. The ChatGPT client is not built yet, so sends answer 409 "not connected" after a token is saved. Step 2 adds the real client.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env   # set ADMIN_PASSWORD
set -a; . ./.env; set +a
.venv/bin/uvicorn index:app --host 127.0.0.1 --port 8000
```

## Calls with the API key

Set `APP_API_KEY` (24+ characters). Send it as `Authorization: Bearer <key>`, as `X-API-Key`, or as `?key=` at the end of the URL.

```text
POST /api/chat/send            {"message": "..."}                    -> 200 answered, or 202 waiting with the chat id
POST /api/chat/send            {"chat_id": "<id>", "message": "..."} -> a follow-up in the same chat
GET  /api/chat/<id>            -> status answered | waiting | failed, and the messages
GET  /api/chat                 -> saved chats
DELETE /api/chat/<id>
```

MCP client config: URL `https://<host>/mcp`, with the header `Authorization: Bearer <key>`.

## Tests

```bash
.venv/bin/python -m pytest -q
```

The tests use a fake ChatGPT and an in-memory store. They make no network calls.
