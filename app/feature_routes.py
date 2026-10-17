"""REST routes for chats. They need an API key or a browser login (see main.py)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Response
from pydantic import BaseModel, Field

from .chat_service import ChatService
from .records import ID_PATTERN

CHAT_ID = Path(pattern=ID_PATTERN)


class ChatSendIn(BaseModel):
    chat_id: str | None = Field(default=None, pattern=ID_PATTERN)
    message: str = Field(min_length=1, max_length=8000)
    model: str | None = Field(default=None, max_length=100)


def chat_router(service: ChatService, guard: Any) -> APIRouter:
    router = APIRouter(prefix="/api/chat", dependencies=[Depends(guard)])

    @router.get("")
    async def list_chats() -> dict[str, Any]:
        return {"chats": await service.list_chats()}

    @router.post("/send")
    async def send(body: ChatSendIn, response: Response) -> dict[str, Any]:
        result = await service.send(chat_id=body.chat_id, message=body.message, model=body.model)
        if result["status"] == "waiting":
            response.status_code = 202  # accepted; read the reply later with GET on this chat id
        return result

    @router.get("/{chat_id}")
    async def get_chat(chat_id: str = CHAT_ID) -> dict[str, Any]:
        return await service.read_chat(chat_id)

    @router.delete("/{chat_id}")
    async def delete_chat(chat_id: str = CHAT_ID) -> dict[str, bool]:
        await service.delete_chat(chat_id)
        return {"ok": True}

    return router
