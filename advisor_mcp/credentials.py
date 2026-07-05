"""Resolve a Claude OAuth access token for calling the Anthropic API.

By default this reuses the token that Claude Code stores for the logged-in
Claude Max / Pro subscription (``~/.claude/.credentials.json``), so no separate
paid API key is needed. Claude Code keeps that token refreshed while it runs; if
it has nonetheless expired we refresh it ourselves using the stored refresh
token and write the new token back, preserving the file's other contents.

Configuration is read from the environment (populated from ``.env`` by the
server before this module is used):

- ``ANTHROPIC_OAUTH_TOKEN``  -- explicit token override; skips the file entirely.
- ``ADVISOR_CREDENTIALS_PATH`` -- path to the credentials JSON
  (default ``~/.claude/.credentials.json``).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import httpx

# Public OAuth client id used by Claude Code. This is not a secret; it is the
# same value shipped in the Claude Code client and required by the token
# endpoint to refresh a subscription token.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"

# Refresh a little before the real expiry to avoid racing the deadline.
_EXPIRY_SKEW_MS = 60_000

_lock = threading.Lock()


class CredentialError(RuntimeError):
    """Raised when no usable OAuth token can be resolved."""


def _credentials_path() -> Path:
    raw = os.environ.get("ADVISOR_CREDENTIALS_PATH")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".claude" / ".credentials.json"


def _read_oauth_block(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CredentialError(
            f"Credentials file not found at {path}. Log in with Claude Code, or set "
            "ANTHROPIC_OAUTH_TOKEN / ADVISOR_CREDENTIALS_PATH in .env."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise CredentialError(f"Could not read credentials at {path}: {exc}") from exc

    oauth = data.get("claudeAiOauth")
    if not isinstance(oauth, dict) or not oauth.get("accessToken"):
        raise CredentialError(
            f"No 'claudeAiOauth.accessToken' found in {path}. "
            "Is this a Claude Code credentials file?"
        )
    return oauth


def _refresh(path: Path, oauth: dict) -> str:
    refresh_token = oauth.get("refreshToken")
    if not refresh_token:
        raise CredentialError(
            "Access token expired and no refresh token is available; "
            "re-authenticate with Claude Code."
        )

    try:
        resp = httpx.post(
            TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
            },
            headers={"content-type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPError as exc:
        raise CredentialError(f"Token refresh failed: {exc}") from exc

    access_token = payload.get("access_token")
    if not access_token:
        raise CredentialError(f"Token refresh returned no access_token: {payload}")

    # expires_in is in seconds; store expiresAt in epoch milliseconds to match
    # the format Claude Code uses.
    expires_at = int(time.time() * 1000) + int(payload.get("expires_in", 0)) * 1000
    _write_back(
        path,
        access_token=access_token,
        refresh_token=payload.get("refresh_token", refresh_token),
        expires_at=expires_at,
    )
    return access_token


def _write_back(path: Path, *, access_token: str, refresh_token: str, expires_at: int) -> None:
    """Persist refreshed tokens without disturbing the rest of the file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    oauth = data.setdefault("claudeAiOauth", {})
    oauth["accessToken"] = access_token
    oauth["refreshToken"] = refresh_token
    oauth["expiresAt"] = expires_at

    tmp = path.with_suffix(path.suffix + ".advisor.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # Writing back is best-effort; a failure here should not break the call
        # since we still return the fresh in-memory token.
        tmp.unlink(missing_ok=True)


def get_access_token() -> str:
    """Return a valid OAuth access token, refreshing it if necessary."""
    override = os.environ.get("ANTHROPIC_OAUTH_TOKEN")
    if override:
        return override.strip()

    with _lock:
        path = _credentials_path()
        oauth = _read_oauth_block(path)
        expires_at = oauth.get("expiresAt", 0)
        now_ms = int(time.time() * 1000)
        if expires_at and now_ms >= expires_at - _EXPIRY_SKEW_MS:
            return _refresh(path, oauth)
        return oauth["accessToken"]
