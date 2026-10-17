"""The session cookie: parsing both NextAuth parts, checking it with ChatGPT, and refusing when it has expired."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.chatgpt_backend import ChatGPTUnreachable
from app.main import create_app
from app.session_cookie import COOKIE_NAME, cookie_header, parse_session_cookies
from app.records import FeatureError
from tests.conftest import ADMIN_PASS, ADMIN_USER, MemoryStore, bearer

PART0 = "A" * 40 + "part0-value"
PART1 = "B" * 30 + "part1-value"
WHOLE = "eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0.sampleTOKENvalue_xyz987"


# ----- parsing ---------------------------------------------------------------------

def test_a_cookie_header_with_both_parts_is_read_in_order():
    raw = f"cookie: {COOKIE_NAME}.1={PART1}; other=1; {COOKIE_NAME}.0={PART0}"
    assert parse_session_cookies(raw) == {"0": PART0, "1": PART1}


def test_one_name_value_per_line_with_both_parts():
    raw = f"{COOKIE_NAME}.0={PART0}\n{COOKIE_NAME}.1={PART1}\n"
    assert parse_session_cookies(raw) == {"0": PART0, "1": PART1}


def test_a_single_plain_cookie_is_kept_whole():
    assert parse_session_cookies(WHOLE) == {"": WHOLE}
    assert parse_session_cookies(f"{COOKIE_NAME}={WHOLE}") == {"": WHOLE}


def test_json_from_a_cookie_extension_is_read():
    raw = '[{"name": "__Secure-next-auth.session-token.0", "value": "%s"}, {"name": "__Secure-next-auth.session-token.1", "value": "%s"}]' % (PART0, PART1)
    assert parse_session_cookies(raw) == {"0": PART0, "1": PART1}


def test_two_bare_values_are_parts_in_the_order_given():
    assert parse_session_cookies(f"{PART0}\n{PART1}") == {"0": PART0, "1": PART1}


def test_a_missing_part_is_named():
    with pytest.raises(FeatureError) as err:
        parse_session_cookies(f"{COOKIE_NAME}.1={PART1}")
    assert err.value.status_code == 422
    assert "Part .0" in err.value.message


def test_a_lone_first_part_is_refused_because_part_one_is_missing():
    with pytest.raises(FeatureError) as err:
        parse_session_cookies(f"{COOKIE_NAME}.0={PART0}")
    assert err.value.status_code == 422
    assert "Part .1" in err.value.message


def test_mixing_a_whole_cookie_with_parts_is_refused():
    with pytest.raises(FeatureError):
        parse_session_cookies(f"{COOKIE_NAME}={WHOLE}; {COOKIE_NAME}.0={PART0}")


def test_nothing_recognisable_is_refused_with_the_help_text():
    with pytest.raises(FeatureError) as err:
        parse_session_cookies("hello world, not a cookie")
    assert COOKIE_NAME in err.value.message


def test_the_request_header_joins_parts_in_order():
    assert cookie_header({"0": PART0, "1": PART1}) == f"{COOKIE_NAME}.0={PART0}; {COOKIE_NAME}.1={PART1}"
    assert cookie_header({"": WHOLE}) == f"{COOKIE_NAME}={WHOLE}"


# ----- saving and checking ----------------------------------------------------------

def test_saving_checks_straight_away_and_reports_the_account(client, backend):
    resp = client.post("/api/session/token", json={"token": f"{COOKIE_NAME}.0={PART0}\n{COOKIE_NAME}.1={PART1}"})
    assert resp.status_code == 200
    check = resp.json()["token"]["check"]
    assert check["valid"] is True
    assert check["account"] == "Test User"
    assert check["checked_at"]
    assert resp.json()["token"]["parts"] == 2
    assert f"{COOKIE_NAME}.0={PART0}; {COOKIE_NAME}.1={PART1}" == backend.checked_headers[-1]


def test_an_expired_session_is_reported_as_invalid(client, backend):
    backend.session_valid = False
    resp = client.post("/api/session/token", json={"token": WHOLE})
    check = resp.json()["token"]["check"]
    assert check["valid"] is False
    assert "not logged in" in check["error"]


def test_a_check_that_cannot_reach_chatgpt_says_so_and_does_not_call_it_expired(client, backend):
    backend.session_unreachable = ChatGPTUnreachable("ChatGPT answered HTTP 403 to the session check.")
    check = client.post("/api/session/check").json()["token"]["check"]
    assert check["valid"] is None
    assert "HTTP 403" in check["error"]


def test_check_again_updates_the_result(client, backend):
    client.post("/api/session/token", json={"token": WHOLE})
    backend.session_valid = False
    check = client.post("/api/session/check").json()["token"]["check"]
    assert check["valid"] is False
    backend.session_valid = True
    assert client.post("/api/session/check").json()["token"]["check"]["valid"] is True


def test_checking_without_a_saved_cookie_is_a_409(client):
    client.delete("/api/session/token")
    resp = client.post("/api/session/check")
    assert resp.status_code == 409
    assert "No session cookie is saved" in resp.json()["detail"]


def test_a_send_is_refused_while_the_last_check_says_expired(client, backend):
    client.post("/api/session/token", json={"token": WHOLE})
    backend.session_valid = False
    client.post("/api/session/check")
    resp = client.post("/api/chat/send", json={"message": "hi"})
    assert resp.status_code == 409
    assert "not logged in" in resp.json()["detail"]


def test_chatgpt_saying_expired_during_a_send_marks_the_session(client, backend):
    client.post("/api/session/token", json={"token": WHOLE})
    backend.expired_on_send = True
    resp = client.post("/api/chat/send", json={"message": "hi"})
    assert resp.status_code == 409
    assert client.get("/api/session").json()["token"]["check"]["valid"] is False


def test_the_saved_cookie_is_never_returned_whole(client):
    client.post("/api/session/token", json={"token": f"{COOKIE_NAME}.0={PART0}\n{COOKIE_NAME}.1={PART1}"})
    text = client.get("/api/session").text
    assert PART0 not in text and PART1 not in text


def test_a_key_cannot_save_or_check_the_session(settings, backend):
    with TestClient(create_app(settings, backend=backend, store=MemoryStore())) as c:
        assert c.post("/api/session/check", headers=bearer()).status_code == 401
