"""The ChatGPT session token: saved once by the admin, masked when shown, never returned in full."""

from __future__ import annotations

import re
from typing import Any

from .records import FeatureError, JsonStore, utc_now

TOKEN_RECORD = "session/token.json"
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._~+/=%-]{20,8000}$")


def clean_token(raw: str) -> str:
    """Accept the bare value, or 'name=value' pasted from a cookie header."""
    value = raw.strip()
    if value.lower().startswith("__secure-next-auth.session-token="):
        value = value.split("=", 1)[1]
    value = value.split(";", 1)[0].strip()
    if not TOKEN_PATTERN.match(value):
        raise FeatureError(422, "That does not look like a ChatGPT session token. Copy the value of __Secure-next-auth.session-token.")
    return value


def mask(token: str) -> str:
    return f"{token[:4]}…{token[-4:]}" if len(token) > 12 else "saved"


class TokenStore:
    def __init__(self, records: JsonStore) -> None:
        self._records = records

    async def get(self) -> str | None:
        record = await self._records.get(TOKEN_RECORD)
        return record.get("token") if record else None

    async def status(self) -> dict[str, Any]:
        record = await self._records.get(TOKEN_RECORD)
        if not record:
            return {"saved": False}
        return {"saved": True, "masked": mask(record["token"]), "saved_at": record["saved_at"]}

    async def save(self, raw: str) -> dict[str, Any]:
        token = clean_token(raw)
        await self._records.put(TOKEN_RECORD, {"token": token, "saved_at": utc_now()})
        return await self.status()

    async def clear(self) -> None:
        await self._records.delete(TOKEN_RECORD)
