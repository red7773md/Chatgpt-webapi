"""The session check against ChatGPT's session endpoint, with a mock transport. No network."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.chatgpt_web import SESSION_URL, ChatGPTWebBackend
from app.chatgpt_backend import ChatGPTUnreachable

COOKIES = "__Secure-next-auth.session-token.0=PART0; __Secure-next-auth.session-token.1=PART1"


def check_with(handler, cookie_header: str = COOKIES):
    backend = ChatGPTWebBackend(transport=httpx.MockTransport(handler))
    return asyncio.run(backend.check_session(cookie_header))


def json_reply(payload, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def test_a_logged_in_session_is_valid_and_names_the_account():
    body = {"accessToken": "tok", "user": {"name": "Ada", "email": "ada@example.com"}, "expires": "2099-01-01"}
    result = check_with(lambda request: json_reply(body))
    assert result.valid is True
    assert result.account == "Ada"


def test_the_email_is_used_when_there_is_no_name():
    body = {"accessToken": "tok", "user": {"email": "ada@example.com"}}
    assert check_with(lambda request: json_reply(body)).account == "ada@example.com"


def test_a_valid_session_without_a_name_or_email_has_no_account():
    body = {"accessToken": "tok", "user": {}}
    result = check_with(lambda request: json_reply(body))
    assert result.valid is True
    assert result.account is None


def test_an_empty_object_means_the_session_is_not_logged_in():
    result = check_with(lambda request: json_reply({}))
    assert result.valid is False
    assert result.account is None


def test_a_session_without_an_access_token_is_not_logged_in():
    result = check_with(lambda request: json_reply({"user": {"name": "Ada"}}))
    assert result.valid is False


def test_the_check_sends_both_cookie_parts_in_order_to_the_session_url():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["cookie"] = request.headers.get("cookie")
        return json_reply({})

    check_with(handler)
    assert seen["url"] == SESSION_URL
    assert seen["cookie"] == COOKIES


def test_an_http_error_status_is_unreachable_not_expired():
    with pytest.raises(ChatGPTUnreachable) as err:
        check_with(lambda request: httpx.Response(403, text="forbidden"))
    assert "HTTP 403" in str(err.value)


def test_a_html_page_instead_of_json_is_unreachable():
    page = httpx.Response(200, text="<html><body>Just a moment...</body></html>", headers={"content-type": "text/html"})
    with pytest.raises(ChatGPTUnreachable) as err:
        check_with(lambda request: page)
    assert "sent a page" in str(err.value)


def test_an_unexpected_json_shape_is_unreachable():
    with pytest.raises(ChatGPTUnreachable):
        check_with(lambda request: json_reply(["not", "an", "object"]))


def test_a_network_failure_is_unreachable_with_the_error_name():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ChatGPTUnreachable) as err:
        check_with(handler)
    assert "ConnectError" in str(err.value)


def test_sending_is_not_built_yet_and_says_so():
    from app.chatgpt_backend import ChatGPTNotReady

    backend = ChatGPTWebBackend()
    with pytest.raises(ChatGPTNotReady):
        asyncio.run(backend.send(COOKIES, "hi", None, None, lambda _id: None))
