"""Saving and checking the ChatGPT session cookie."""

from __future__ import annotations

import asyncio
from typing import Any

from .chatgpt_backend import ChatBackend, ChatGPTUnreachable
from .records import FeatureError
from .token_store import TokenStore

CHECK_TIMEOUT_SECONDS = 20.0
EXPIRED_MESSAGE = "ChatGPT says this session is not logged in. Copy a fresh session cookie from chatgpt.com and save it again."


class SessionService:
    def __init__(self, backend: ChatBackend, tokens: TokenStore) -> None:
        self._backend = backend
        self._tokens = tokens

    async def save(self, raw: str) -> dict[str, Any]:
        await self._tokens.save(raw)
        return await self.check()

    async def check(self) -> dict[str, Any]:
        header = await self._tokens.header()
        if header is None:
            raise FeatureError(409, "No session cookie is saved. Save one first.")
        try:
            result = await asyncio.wait_for(self._backend.check_session(header), CHECK_TIMEOUT_SECONDS)
        except (ChatGPTUnreachable, asyncio.TimeoutError) as exc:
            detail = str(exc) or "The check timed out. Try again."
            await self._tokens.record_check(valid=None, account=None, error=detail)
        else:
            if result.valid:
                await self._tokens.record_check(valid=True, account=result.account, error=None)
            else:
                await self._tokens.record_check(valid=False, account=None, error=EXPIRED_MESSAGE)
        return await self._tokens.status()
