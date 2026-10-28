"""'Sign in with Notion' (OAuth 2.0 for public integrations).

Streamlit starts a fresh session when the browser comes back from Notion, so
anything the person typed would be lost. To avoid that, their answers ride
along inside the OAuth ``state`` parameter: compressed, timestamped and
HMAC-signed with the client secret, so a tampered or stale state is rejected.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import zlib
from urllib.parse import urlencode

import requests

_BASE = os.environ.get("NOTION_API_BASE", "https://api.notion.com/v1")
AUTHORIZE_URL = f"{_BASE}/oauth/authorize"
TOKEN_URL = f"{_BASE}/oauth/token"
STATE_MAX_AGE = 15 * 60


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, message: str) -> str:
    return _b64(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest())[:32]


def make_state(secret: str, payload: dict, now: float | None = None) -> str:
    data = _b64(zlib.compress(json.dumps(payload, separators=(",", ":")).encode(), 9))
    ts = str(int(now if now is not None else time.time()))
    return f"{data}.{ts}.{_sign(secret, data + '.' + ts)}"


def read_state(secret: str, state: str, now: float | None = None, max_age: int = STATE_MAX_AGE) -> dict:
    try:
        data, ts, sig = state.split(".")
    except ValueError as e:
        raise ValueError("Malformed sign-in state") from e
    if not hmac.compare_digest(sig, _sign(secret, data + "." + ts)):
        raise ValueError("Sign-in state failed verification")
    if (now if now is not None else time.time()) - int(ts) > max_age:
        raise ValueError("Sign-in took too long. Please try again")
    return json.loads(zlib.decompress(_unb64(data)))


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": client_id, "response_type": "code", "owner": "user",
        "redirect_uri": redirect_uri, "state": state,
    })


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str,
                  session: requests.Session | None = None) -> dict:
    """Swap the one-time code for an access token. Returns Notion's full token response."""
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = (session or requests).post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/json"},
        json={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
        timeout=30,
    )
    data = resp.json() if resp.content else {}
    if resp.status_code != 200 or "access_token" not in data:
        raise ValueError(data.get("error_description") or data.get("message") or "Notion sign-in failed")
    return data
