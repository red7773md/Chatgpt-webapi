"""Reads the ChatGPT session cookie the way the browser holds it.

NextAuth splits a long session cookie into parts: __Secure-next-auth.session-token.0,
.1, and so on, and joins them in order. A short one is a single cookie with no
number. Accepted input, in any of these shapes:

1. A cookie header, e.g. "cookie: __Secure-next-auth.session-token.0=...; __Secure-next-auth.session-token.1=..."
2. One "name=value" per line, with both parts.
3. A JSON object {name: value} or a list [{"name": ..., "value": ...}] (cookie-export extensions).
4. Bare values: one value = the whole cookie; several values = parts .0, .1, ... in the order given.

Everything except the session parts is dropped. Only the cookie values are kept.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .records import FeatureError

COOKIE_NAME = "__Secure-next-auth.session-token"
_PART = re.compile(r"^" + re.escape(COOKIE_NAME) + r"(?:\.(\d+))?$")
VALUE_PATTERN = re.compile(r"^[A-Za-z0-9._~+/=%-]{20,8000}$")
HELP = (
    f"Paste {COOKIE_NAME}. If the browser shows it as two cookies (.0 and .1), paste both: "
    "the cookie header or one 'name=value' per line."
)


def parse_session_cookies(raw: str) -> dict[str, str]:
    """Return {"": value} for a single cookie, or {"0": v0, "1": v1, ...} for parts, in order."""
    text = (raw or "").strip()
    if not text:
        raise FeatureError(422, HELP)

    pairs: list[tuple[str, str]] = []
    bare: list[str] = []
    data: Any = None
    try:
        data = json.loads(text)
    except ValueError:
        data = None

    if isinstance(data, dict):
        pairs = [(str(name), str(value)) for name, value in data.items()]
    elif isinstance(data, list):
        pairs = [(str(c.get("name", "")), str(c.get("value", ""))) for c in data if isinstance(c, dict)]
    else:
        for part in re.split(r"[;\n\r]+", text):
            part = re.sub(r"^\s*cookie:\s*", "", part.strip(), flags=re.IGNORECASE)
            if not part:
                continue
            if "=" in part:
                name, value = part.split("=", 1)
                pairs.append((name.strip(), value.strip()))
            else:
                bare.append(part)

    parts: dict[str, str] = {}
    for name, value in pairs:
        match = _PART.match(name)
        if match:
            parts[match.group(1) or ""] = value.strip()

    if not parts and bare:
        if len(bare) == 1:
            parts[""] = bare[0]
        else:
            parts = {str(i): value for i, value in enumerate(bare)}

    if not parts:
        raise FeatureError(422, HELP)
    if "" in parts and len(parts) > 1:
        raise FeatureError(422, "Paste either the whole cookie or its .0/.1 parts, not both kinds.")

    if "" not in parts:
        numbers = sorted(int(k) for k in parts)
        if numbers != list(range(len(numbers))):
            missing = sorted(set(range(numbers[-1] + 1)) - set(numbers))
            raise FeatureError(422, f"Part .{missing[0]} of the session cookie is missing. Paste every part, .0 then .1 and so on.")
        if len(numbers) < 2:
            # A cookie this long is split by the browser, so a lone .0 always means .1 was left out.
            raise FeatureError(422, "Part .1 of the session cookie is missing. The browser splits this cookie into .0 and .1; paste both.")
        parts = {str(i): parts[str(i)] for i in range(len(numbers))}

    for key, value in parts.items():
        if not VALUE_PATTERN.match(value):
            label = f"{COOKIE_NAME}.{key}" if key else COOKIE_NAME
            raise FeatureError(422, f"The value of {label} does not look right. Copy it again from the browser.")
    return parts


def cookie_header(parts: dict[str, str]) -> str:
    """The Cookie header for requests to ChatGPT, parts in order."""
    return "; ".join(f"{COOKIE_NAME}{'.' + key if key else ''}={value}" for key, value in parts.items())


def mask(parts: dict[str, str]) -> str:
    first = next(iter(parts.values()))
    last = list(parts.values())[-1]
    return f"{first[:4]}…{last[-4:]}" if len(first) + len(last) > 12 else "saved"
