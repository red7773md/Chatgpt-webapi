"""The seam between the app and ChatGPT.

The chat service talks only to this interface. The real client (step 2) implements
it against ChatGPT's web endpoints. Tests use a fake. Until the real client exists,
`NotConnectedBackend` answers every call with a plain 409.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class ChatGPTNotReady(RuntimeError):
    """No usable ChatGPT session. The message is safe to show the admin."""


@dataclass(frozen=True)
class Reply:
    id: str  # ChatGPT's message id for the assistant message
    text: str
    finished: bool


class ChatBackend(Protocol):
    async def send(
        self,
        token: str,
        message: str,
        model: str | None,
        conversation_id: str | None,
        on_conversation: Callable[[str], None],
    ) -> Reply | None:
        """Send a message. Calls on_conversation with the conversation id as soon as it is known.
        Returns the finished reply, or None if ChatGPT had not finished when the call was cut off."""

    async def latest_reply(self, token: str, conversation_id: str) -> Reply | None:
        """The newest assistant message in the conversation, finished or not."""


class NotConnectedBackend:
    async def send(self, token, message, model, conversation_id, on_conversation):
        raise ChatGPTNotReady("ChatGPT is not connected yet. Save a session token first.")

    async def latest_reply(self, token, conversation_id):
        raise ChatGPTNotReady("ChatGPT is not connected yet. Save a session token first.")
