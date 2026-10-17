"""The seam between the app and ChatGPT.

The chat service and the session service talk only to this interface.
`chatgpt_web.ChatGPTWebBackend` implements it against ChatGPT's web endpoints.
Tests use a fake.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class ChatGPTNotReady(RuntimeError):
    """ChatGPT cannot be used right now. The message is safe to show the admin."""


class ChatGPTSessionExpired(ChatGPTNotReady):
    """ChatGPT answered that the saved session is no longer logged in."""


class ChatGPTUnreachable(RuntimeError):
    """ChatGPT could not be asked: network trouble, a block, or an unexpected page. Safe to show."""


@dataclass(frozen=True)
class SessionCheck:
    valid: bool
    account: str | None  # the account name or email, if ChatGPT said so


@dataclass(frozen=True)
class Reply:
    id: str  # ChatGPT's message id for the assistant message
    text: str
    finished: bool


class ChatBackend(Protocol):
    async def check_session(self, cookie_header: str) -> SessionCheck:
        """Ask ChatGPT whether the cookie is logged in. Raises ChatGPTUnreachable if it cannot tell."""

    async def send(
        self,
        cookie_header: str,
        message: str,
        model: str | None,
        conversation_id: str | None,
        on_conversation: Callable[[str], None],
    ) -> Reply | None:
        """Send a message. Calls on_conversation with the conversation id as soon as it is known.
        Returns the finished reply, or None if ChatGPT had not finished when the call was cut off."""

    async def latest_reply(self, cookie_header: str, conversation_id: str) -> Reply | None:
        """The newest assistant message in the conversation, finished or not."""


class NotConnectedBackend:
    """Used in tests that do not need ChatGPT."""

    async def check_session(self, cookie_header):
        raise ChatGPTUnreachable("ChatGPT is not reachable from this test setup.")

    async def send(self, cookie_header, message, model, conversation_id, on_conversation):
        raise ChatGPTNotReady("ChatGPT is not connected yet.")

    async def latest_reply(self, cookie_header, conversation_id):
        raise ChatGPTNotReady("ChatGPT is not connected yet.")
