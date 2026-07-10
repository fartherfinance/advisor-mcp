"""Resolve a Claude credential for calling the Anthropic API.

By default this reuses whatever credential Claude Code stores for the local
login, so no separate configuration is needed. Resolution order:

1. ``ANTHROPIC_OAUTH_TOKEN``   -- explicit override from the environment/.env.
2. Credentials file            -- ``~/.claude/.credentials.json`` (how Claude
   Code stores the OAuth token on Linux), or ``ADVISOR_CREDENTIALS_PATH``.
3. macOS Keychain OAuth token  -- service ``Claude Code-credentials``, key
   ``claudeAiOauth`` (how Claude Code stores a Max/Pro subscription login
   on macOS).
4. macOS Keychain API key      -- service ``Claude Code`` (how Claude Code
   stores an API-key login on macOS).

OAuth access tokens are refreshed if expired, using the stored refresh token,
and the new token is written back to wherever it came from (file or Keychain)
so Claude Code's copy stays valid -- refresh tokens rotate on use.
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

# Public OAuth client id used by Claude Code. This is not a secret; it is the
# same value shipped in the Claude Code client and required by the token
# endpoint to refresh a subscription token.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"

KEYCHAIN_OAUTH_SERVICE = "Claude Code-credentials"
KEYCHAIN_API_KEY_SERVICE = "Claude Code"

# Refresh a little before the real expiry to avoid racing the deadline.
_EXPIRY_SKEW_MS = 60_000

_lock = threading.Lock()


class CredentialError(RuntimeError):
    """Raised when no usable credential can be resolved."""


@dataclass(frozen=True)
class Credential:
    token: str
    is_api_key: bool


def _looks_like_api_key(token: str) -> bool:
    return token.startswith("sk-ant-api")


def _credentials_path() -> Path:
    raw = os.environ.get("ADVISOR_CREDENTIALS_PATH")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".claude" / ".credentials.json"


def _extract_oauth_block(data: dict, source: str) -> dict:
    oauth = data.get("claudeAiOauth")
    if not isinstance(oauth, dict) or not oauth.get("accessToken"):
        raise CredentialError(
            f"No 'claudeAiOauth.accessToken' found in {source}. "
            "Is this a Claude Code credentials store?"
        )
    return oauth


def _read_file_oauth(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CredentialError(f"Could not read credentials at {path}: {exc}") from exc
    return _extract_oauth_block(data, str(path))


def _keychain_read(service: str) -> str | None:
    """Return the password stored for *service*, or None if absent."""
    if sys.platform != "darwin":
        return None
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.rstrip("\n") or None


def _keychain_write(service: str, payload: str) -> None:
    """Best-effort update of a Keychain item (``-U`` upserts)."""
    subprocess.run(
        [
            "security", "add-generic-password", "-U",
            "-a", getpass.getuser(),
            "-s", service,
            "-w", payload,
        ],
        capture_output=True,
    )


def _refresh(oauth: dict, persist) -> str:
    """Refresh an expired OAuth token and persist it via *persist(oauth)*."""
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
    oauth["accessToken"] = access_token
    oauth["refreshToken"] = payload.get("refresh_token", refresh_token)
    oauth["expiresAt"] = int(time.time() * 1000) + int(payload.get("expires_in", 0)) * 1000
    persist(oauth)
    return access_token


def _resolve_oauth(oauth: dict, persist) -> str:
    expires_at = oauth.get("expiresAt", 0)
    now_ms = int(time.time() * 1000)
    if expires_at and now_ms >= expires_at - _EXPIRY_SKEW_MS:
        return _refresh(oauth, persist)
    return oauth["accessToken"]


def _persist_to_file(path: Path):
    def persist(oauth: dict) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        data.setdefault("claudeAiOauth", {}).update(
            accessToken=oauth["accessToken"],
            refreshToken=oauth["refreshToken"],
            expiresAt=oauth["expiresAt"],
        )
        tmp = path.with_suffix(path.suffix + ".advisor.tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            # Best-effort; the fresh in-memory token is still returned.
            tmp.unlink(missing_ok=True)

    return persist


def _persist_to_keychain(raw: str):
    def persist(oauth: dict) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        data.setdefault("claudeAiOauth", {}).update(
            accessToken=oauth["accessToken"],
            refreshToken=oauth["refreshToken"],
            expiresAt=oauth["expiresAt"],
        )
        _keychain_write(KEYCHAIN_OAUTH_SERVICE, json.dumps(data))

    return persist


def get_credential() -> Credential:
    """Return a valid credential, refreshing OAuth tokens if necessary."""
    override = os.environ.get("ANTHROPIC_OAUTH_TOKEN")
    if override:
        token = override.strip()
        return Credential(token, _looks_like_api_key(token))

    with _lock:
        # Linux-style credentials file (or explicit ADVISOR_CREDENTIALS_PATH).
        path = _credentials_path()
        if path.exists():
            oauth = _read_file_oauth(path)
            return Credential(_resolve_oauth(oauth, _persist_to_file(path)), False)

        # macOS Keychain: subscription OAuth login.
        raw = _keychain_read(KEYCHAIN_OAUTH_SERVICE)
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {}
            oauth = data.get("claudeAiOauth")
            if isinstance(oauth, dict) and oauth.get("accessToken"):
                return Credential(
                    _resolve_oauth(oauth, _persist_to_keychain(raw)), False
                )

        # macOS Keychain: API-key login.
        api_key = _keychain_read(KEYCHAIN_API_KEY_SERVICE)
        if api_key and _looks_like_api_key(api_key.strip()):
            return Credential(api_key.strip(), True)

    raise CredentialError(
        "No Claude credential found. Checked ANTHROPIC_OAUTH_TOKEN, "
        f"{path}, and the macOS Keychain ('{KEYCHAIN_OAUTH_SERVICE}' OAuth login, "
        f"'{KEYCHAIN_API_KEY_SERVICE}' API key). Log in with Claude Code, or set "
        "ANTHROPIC_OAUTH_TOKEN / ADVISOR_CREDENTIALS_PATH in .env."
    )


def get_access_token() -> str:
    """Backwards-compatible helper returning just the token string."""
    return get_credential().token
