# ChatGPT Archive

A single-admin service over ChatGPT's web interface, with two ways in:

- **REST** at `/api/chat/...`
- **MCP** at `/mcp`, with tools `chatgpt_send`, `chatgpt_get_chat`, `chatgpt_list_chats`, `chatgpt_delete_chat`

Both use the same chat service and the same records.

**This is unofficial.** It uses ChatGPT's web endpoints with your browser session token, not the OpenAI API. That may break when ChatGPT changes, and it may breach OpenAI's terms. Use an account you can afford to lose access to.

## Status

Step 1 (skeleton) is in place: the REST routes, the MCP endpoint, the session cookie store with a check against ChatGPT, the API key, and tests. Sending messages to ChatGPT is not built yet; that is step 2.

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

## Session cookie

1. In Chrome, log in to chatgpt.com, open DevTools, go to Application → Cookies → `https://chatgpt.com`.
2. Copy `__Secure-next-auth.session-token`. If the browser lists it twice, as `__Secure-next-auth.session-token.0` and `.1`, copy both values.
3. Paste into the admin page either both as `name=value` lines, or the whole cookie header. A single unsplit value is accepted as it is. A lone `.0` is refused, because the browser always splits the cookie into both parts when it is split.

Saving checks the cookie with ChatGPT at once. The page then shows one of three states:

- **session valid**, with the account name and the time of the check;
- **not logged in**, which means ChatGPT rejected the cookie; copy a fresh one and save again;
- **could not check**, with the reason (ChatGPT blocked the request, answered an error, or could not be reached). This does not mean the cookie is bad.

CHECK SESSION repeats the check. While the last check says not logged in, sends are refused with 409 and the same message.

Admin-only routes (the admin login is needed; the API key is refused):

```text
GET    /api/session           -> saved?, masked value, parts, last check
POST   /api/session/token     {"token": "..."}   -> saves, then checks
POST   /api/session/check     -> checks the saved cookie again
DELETE /api/session/token     -> removes it
```

Limits: ChatGPT can rotate the cookie when it is used, and this app does not save a rotated cookie yet. A cookie can therefore stop working after a while, which the next check reports as not logged in. ChatGPT may also refuse requests from the hosting provider's servers; that shows as "could not check".

## Tests

```bash
.venv/bin/python -m pytest -q
```

The tests use a fake ChatGPT and an in-memory store. They make no network calls.
