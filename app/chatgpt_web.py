"""ChatGPT's web endpoints, called with the admin's session cookie.

Session check: GET https://chatgpt.com/api/auth/session. A logged-in cookie gets JSON
with an accessToken and the user. A dead cookie gets an empty object. Anything else
(a block page, an error status, a network failure) means the check could not tell,
and it is reported as ChatGPTUnreachable rather than as "invalid".

Sending messages is not built yet. Those calls raise ChatGPTNotReady until step 2.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx

from .chatgpt_backend import ChatGPTNotReady, ChatGPTUnreachable, Reply, SessionCheck

SESSION_URL = "https://chatgpt.com/api/auth/session"
TIMEOUT_SECONDS = 15.0
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://chatgpt.com/",
}


MAX_DETAIL_CHARS = 160
log = logging.getLogger("chatgpt_webui")


def _snippet(text: str, cookie_header: str) -> str:
    """The start of ChatGPT's reply, shortened, with no cookie value in it."""
    snippet = " ".join(text.split())[:MAX_DETAIL_CHARS]
    for pair in cookie_header.split(";"):
        value = pair.partition("=")[2].strip()
        if len(value) >= 8:
            snippet = snippet.replace(value, "[cookie]")
    return snippet


def _is_bot_challenge(res: httpx.Response) -> bool:
    return res.headers.get("cf-mitigated", "").lower() == "challenge" or "just a moment" in res.text.lower()


def _refusal(res: httpx.Response, cookie_header: str) -> str:
    """Say what ChatGPT answered. A bot-protection block is named as one, not blamed on the cookie."""
    snippet = _snippet(res.text, cookie_header)
    log.warning("session check refused: HTTP %s, cf-mitigated=%r, reply starts: %r",
                res.status_code, res.headers.get("cf-mitigated"), snippet)
    if _is_bot_challenge(res):
        return (
            f"ChatGPT's bot protection blocked this server (HTTP {res.status_code}). "
            "The cookie was not judged, so this is about the server's network, not the cookie."
        )
    if snippet:
        return f'ChatGPT refused the session check with HTTP {res.status_code}. Its reply starts: "{snippet}"'
    return f"ChatGPT refused the session check with HTTP {res.status_code} and sent no reply."


class ChatGPTWebBackend:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport  # tests inject a mock transport

    async def check_session(self, cookie_header: str) -> SessionCheck:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, headers=BROWSER_HEADERS, transport=self._transport) as client:
                res = await client.get(SESSION_URL, headers={"Cookie": cookie_header})
        except httpx.HTTPError as exc:
            raise ChatGPTUnreachable(f"Could not reach ChatGPT ({type(exc).__name__}). Try the check again in a moment.") from exc

        if res.status_code != 200:
            raise ChatGPTUnreachable(_refusal(res, cookie_header))
        try:
            data: Any = res.json()
        except ValueError as exc:
            if _is_bot_challenge(res):
                raise ChatGPTUnreachable(_refusal(res, cookie_header)) from exc
            snippet = _snippet(res.text, cookie_header)
            raise ChatGPTUnreachable(
                f'ChatGPT sent a page instead of the session data. It starts: "{snippet}"'
            ) from exc
        if not isinstance(data, dict):
            raise ChatGPTUnreachable("ChatGPT sent an unexpected answer to the session check.")

        if data.get("accessToken") and isinstance(data.get("user"), dict):
            user = data["user"]
            return SessionCheck(valid=True, account=str(user.get("name") or user.get("email") or "") or None)
        return SessionCheck(valid=False, account=None)

    async def send(
        self,
        cookie_header: str,
        message: str,
        model: str | None,
        conversation_id: str | None,
        on_conversation: Callable[[str], None],
    ) -> Reply | None:
        raise ChatGPTNotReady("Sending messages to ChatGPT is not built yet. Session checks work.")

    async def latest_reply(self, cookie_header: str, conversation_id: str) -> Reply | None:
        raise ChatGPTNotReady("Reading ChatGPT replies is not built yet. Session checks work.")
