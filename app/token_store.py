"""The saved ChatGPT session cookie and the result of its last check. Never returned in full."""

from __future__ import annotations

from typing import Any

from .records import JsonStore, utc_now
from .session_cookie import cookie_header, mask, parse_session_cookies

TOKEN_RECORD = "session/token.json"


def _empty_check() -> dict[str, Any]:
    return {"valid": None, "account": None, "checked_at": None, "error": None}


class TokenStore:
    def __init__(self, records: JsonStore) -> None:
        self._records = records

    async def cookies(self) -> dict[str, str] | None:
        record = await self._records.get(TOKEN_RECORD)
        return record.get("cookies") if record else None

    async def header(self) -> str | None:
        cookies = await self.cookies()
        return cookie_header(cookies) if cookies else None

    async def check_result(self) -> dict[str, Any] | None:
        record = await self._records.get(TOKEN_RECORD)
        return record.get("check") if record else None

    async def status(self) -> dict[str, Any]:
        record = await self._records.get(TOKEN_RECORD)
        if not record:
            return {"saved": False}
        return {
            "saved": True,
            "masked": mask(record["cookies"]),
            "parts": len(record["cookies"]),
            "saved_at": record["saved_at"],
            "check": record.get("check") or _empty_check(),
        }

    async def save(self, raw: str) -> None:
        cookies = parse_session_cookies(raw)  # raises a 422 with a plain message
        await self._records.put(
            TOKEN_RECORD,
            {"cookies": cookies, "saved_at": utc_now(), "check": _empty_check()},
        )

    async def record_check(self, valid: bool | None, account: str | None, error: str | None) -> None:
        record = await self._records.get(TOKEN_RECORD)
        if not record:
            return
        record["check"] = {"valid": valid, "account": account, "checked_at": utc_now(), "error": error}
        await self._records.put(TOKEN_RECORD, record)

    async def clear(self) -> None:
        await self._records.delete(TOKEN_RECORD)
