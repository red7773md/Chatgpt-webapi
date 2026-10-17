"""Chat: conversations with ChatGPT, saved as JSON records in the store.

A send waits a short time for the reply. If ChatGPT is still writing, the chat is
saved with a pending reply and its id is returned at once. Each later read checks
ChatGPT for the reply, no more often than the check gap allows, and gives up after
30 minutes. A follow-up sent while a reply is pending is refused.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .checks import check_is_due, error_text, seconds_since
from .chatgpt_backend import ChatBackend, ChatGPTNotReady, ChatGPTSessionExpired, Reply
from .records import FeatureError, JsonStore, new_id, utc_now
from .session_service import EXPIRED_MESSAGE
from .token_store import TokenStore

log = logging.getLogger("chatgpt_webui")

CHAT_INDEX = "chats/index.json"
MAX_MESSAGE_CHARS = 8000
SEND_WAIT_SECONDS = 25.0  # how long a send waits for the reply before returning the chat id
CHECK_SECONDS = 20.0  # the gap between checks of a pending reply
READ_TIMEOUT_SECONDS = 30.0  # one check at ChatGPT
REPLY_WAIT_SECONDS = 30 * 60  # a reply still missing after this is given up
TITLE_CHARS = 60


def record_name(chat_id: str) -> str:
    return f"chats/{chat_id}.json"


def chat_status(record: dict[str, Any]) -> str:
    """"answered" when nothing is pending, "waiting" while ChatGPT writes, "failed" if it gave up."""
    pending = record.get("pending")
    if not pending:
        return "answered"
    return "failed" if pending.get("error") else "waiting"


def _summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "title": record["title"],
        "model": record.get("model"),
        "updated_at": record["updated_at"],
        "message_count": len(record["messages"]),
        "status": chat_status(record),
    }


def _model_turn(text: str, now: str) -> dict[str, Any]:
    return {"id": new_id(), "role": "model", "text": text, "created_at": now}


class ChatService:
    def __init__(self, backend: ChatBackend, records: JsonStore, tokens: TokenStore) -> None:
        self._backend = backend
        self._records = records
        self._tokens = tokens
        self._checking: set[str] = set()

    async def list_chats(self) -> list[dict[str, Any]]:
        return await self._records.index(CHAT_INDEX)

    async def get_chat(self, chat_id: str) -> dict[str, Any]:
        record = await self._records.get(record_name(chat_id))
        if record is None:
            raise FeatureError(404, "Chat not found.")
        return record

    async def read_chat(self, chat_id: str) -> dict[str, Any]:
        """The chat as it is now. A pending reply is checked at ChatGPT if the gap has passed."""
        record = await self.get_chat(chat_id)
        pending = record.get("pending")
        if pending and not pending.get("error") and chat_id not in self._checking and check_is_due(pending, CHECK_SECONDS):
            self._checking.add(chat_id)
            try:
                record = await self._check_reply(record)
            finally:
                self._checking.discard(chat_id)
        return {**record, "status": chat_status(record)}

    async def delete_chat(self, chat_id: str) -> None:
        await self.get_chat(chat_id)  # raises 404 for unknown ids
        await self._records.delete(record_name(chat_id))
        await self._records.remove_from_index(CHAT_INDEX, chat_id)

    async def send(self, chat_id: str | None, message: str, model: str | None) -> dict[str, Any]:
        message = message.strip()
        if not message:
            raise FeatureError(422, "Message is empty.")
        if len(message) > MAX_MESSAGE_CHARS:
            raise FeatureError(422, f"Message is longer than {MAX_MESSAGE_CHARS} characters.")
        header = await self._tokens.header()
        if not header:
            raise FeatureError(409, "ChatGPT is not connected. Save a session cookie first.")
        check = await self._tokens.check_result()
        if check and check.get("valid") is False:
            raise FeatureError(409, EXPIRED_MESSAGE)

        record = await self.get_chat(chat_id) if chat_id else self._new_record(model)
        if chat_status(record) == "waiting":
            raise FeatureError(409, "The last message is still being answered. Check the chat, then send again when the reply is in.")
        if not record["title"]:
            record["title"] = " ".join(message.split())[:TITLE_CHARS]

        now = utc_now()
        user_turn = {"id": new_id(), "role": "user", "text": message, "created_at": now}
        known = {"conversation_id": record.get("conversation_id")}

        def remember(cid: str) -> None:
            known["conversation_id"] = cid

        try:
            reply = await asyncio.wait_for(
                self._backend.send(header, message, model, known["conversation_id"], remember),
                SEND_WAIT_SECONDS,
            )
        except asyncio.TimeoutError:
            reply = None  # ChatGPT is still writing; read it from the conversation later
        except ChatGPTSessionExpired as exc:
            await self._tokens.record_check(valid=False, account=None, error=EXPIRED_MESSAGE)
            raise FeatureError(409, EXPIRED_MESSAGE) from exc
        except ChatGPTNotReady as exc:
            raise FeatureError(409, str(exc)) from exc

        record["messages"].append(user_turn)
        record["updated_at"] = now
        record["model"] = model or record.get("model")
        record["conversation_id"] = known["conversation_id"]
        reply_turn = None
        if reply is not None and reply.finished:
            reply_turn = _model_turn(reply.text.strip(), now)
            record["messages"].append(reply_turn)
            record["last_reply_id"] = reply.id
            record["pending"] = None
        else:
            record["pending"] = {
                "turn_id": user_turn["id"],
                "after_reply_id": record.get("last_reply_id"),  # a reply with this id is not the new one
                "since": now,
                "checked_at": None,
                "check_failures": 0,
                "last_check_error": None,
            }
            if not record["conversation_id"]:
                record["pending"]["error"] = "ChatGPT did not confirm the message in time. Send it again."

        await self._records.put(record_name(record["id"]), record)
        await self._records.upsert_index(CHAT_INDEX, _summary(record))
        messages = [user_turn] + ([reply_turn] if reply_turn else [])
        return {"chat": _summary(record), "status": chat_status(record), "messages": messages}

    async def _check_reply(self, record: dict[str, Any]) -> dict[str, Any]:
        pending = record["pending"]
        cid = record["conversation_id"]
        try:
            header = await self._tokens.header()
            if not header:
                raise ChatGPTNotReady("ChatGPT is not connected. Save a session cookie first.")
            latest = await asyncio.wait_for(self._backend.latest_reply(header, cid), READ_TIMEOUT_SECONDS)
        except ChatGPTSessionExpired as exc:
            await self._tokens.record_check(valid=False, account=None, error=EXPIRED_MESSAGE)
            return await self._record_check_failure(record, exc)
        except (ChatGPTNotReady, asyncio.TimeoutError, OSError) as exc:
            return await self._record_check_failure(record, exc)

        now = utc_now()
        if not _is_new_reply(latest, pending.get("after_reply_id")):
            if seconds_since(pending["since"]) > REPLY_WAIT_SECONDS:
                detail = f" Last check: {pending['last_check_error']}." if pending.get("last_check_error") else ""
                pending["error"] = f"ChatGPT did not reply within 30 minutes. Send the message again.{detail}"
                log.warning("no reply after %d s; giving up on chat %s", REPLY_WAIT_SECONDS, record["id"])
            else:
                pending["checked_at"] = now
                pending["check_failures"] = 0
                pending["last_check_error"] = None
            record["updated_at"] = now
            await self._records.put(record_name(record["id"]), record)
            return record

        record["messages"].append(_model_turn(latest.text.strip(), now))
        record["last_reply_id"] = latest.id
        record["pending"] = None
        record["updated_at"] = now
        await self._records.put(record_name(record["id"]), record)
        await self._records.upsert_index(CHAT_INDEX, _summary(record))
        return record

    async def _record_check_failure(self, record: dict[str, Any], exc: Exception) -> dict[str, Any]:
        pending = record["pending"]
        pending["check_failures"] = int(pending.get("check_failures") or 0) + 1
        pending["last_check_error"] = error_text(exc)
        pending["checked_at"] = utc_now()
        record["updated_at"] = pending["checked_at"]
        log.warning("chat check failed for %s (%d in a row): %s", record["id"], pending["check_failures"], pending["last_check_error"])
        await self._records.put(record_name(record["id"]), record)
        return record

    def _new_record(self, model: str | None) -> dict[str, Any]:
        now = utc_now()
        return {
            "id": new_id(),
            "title": "",
            "model": model or None,
            "conversation_id": None,
            "last_reply_id": None,
            "created_at": now,
            "updated_at": now,
            "messages": [],
            "pending": None,
        }


def _is_new_reply(latest: Reply | None, after_reply_id: str | None) -> bool:
    return latest is not None and latest.finished and bool(latest.text.strip()) and latest.id != after_reply_id
