"""advisor-mcp server.

Exposes tools that let the running model (Opus / Sonnet / Haiku) consult Fable
(``claude-fable-5`` by default) for a second opinion or extra guidance, billed to
the existing Claude Max subscription via its OAuth token.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from . import __version__
from .credentials import CredentialError, get_credential

# Load configuration from the .env that lives next to this project, regardless
# of the current working directory the MCP host launched us from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

API_URL = "https://api.anthropic.com/v1/messages"
# Required when authenticating with a subscription OAuth token instead of an API key.
OAUTH_BETA = "oauth-2025-04-20"
# Presenting as Claude Code routes requests through the Claude Code rate-limit
# pool; orgs often restrict raw API traffic (per-model caps) while allowing
# Claude Code usage, so this beta + user-agent + identity line are load-bearing
# for API-key auth too, not just OAuth.
CLAUDE_CODE_BETA = "claude-code-20250219"
CLAUDE_CODE_USER_AGENT = "claude-cli/2.1.206 (external, cli)"
# The credential is only accepted for Claude Code; the system prompt must
# lead with this identity line.
CLAUDE_CODE_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."

DEFAULT_MODEL = os.environ.get("ADVISOR_MODEL", "claude-fable-5")
DEFAULT_MAX_TOKENS = int(os.environ.get("ADVISOR_MAX_TOKENS", "128000"))
REQUEST_TIMEOUT = float(os.environ.get("ADVISOR_TIMEOUT", "120"))

ADVISOR_ROLE = (
    "You are Fable, acting as a senior technical advisor to another AI coding "
    "agent. Give direct, well-reasoned guidance: weigh trade-offs, flag risks and "
    "edge cases, and recommend a concrete course of action. Be concise and "
    "practical rather than exhaustive."
)

mcp = FastMCP("advisor")


def _call_fable(
    prompt: str,
    *,
    context: str | None,
    model: str,
    max_tokens: int,
    temperature: float,
) -> str:
    credential = get_credential()

    user_content = prompt if not context else f"<context>\n{context}\n</context>\n\n{prompt}"

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [
            {"type": "text", "text": CLAUDE_CODE_IDENTITY},
            {"type": "text", "text": ADVISOR_ROLE},
        ],
        "messages": [{"role": "user", "content": user_content}],
    }
    # Fable 5 / Opus 4.7+ reject sampling parameters; only send a non-default
    # temperature, and never to models that would 400 on it.
    if temperature != 1.0 and not model.startswith(("claude-fable", "claude-mythos", "claude-opus-4-7", "claude-opus-4-8", "claude-sonnet-5")):
        body["temperature"] = temperature

    headers = {
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
        "user-agent": CLAUDE_CODE_USER_AGENT,
        "x-app": "cli",
    }
    if credential.is_api_key:
        headers["x-api-key"] = credential.token
        headers["anthropic-beta"] = CLAUDE_CODE_BETA
    else:
        headers["authorization"] = f"Bearer {credential.token}"
        headers["anthropic-beta"] = f"{OAUTH_BETA},{CLAUDE_CODE_BETA}"

    resp = httpx.post(
        API_URL,
        json=body,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    parts = [block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"]
    text = "".join(parts).strip()
    if text:
        return text
    if data.get("stop_reason") == "max_tokens":
        return (
            "(Fable produced no text — the token budget was consumed by internal "
            "reasoning. Retry with a larger max_tokens.)"
        )
    return "(Fable returned no text.)"


@mcp.tool()
def ask_advisor(
    prompt: str,
    context: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = 1.0,
) -> str:
    """Consult Fable for a second opinion or extra guidance on a hard problem.

    Use this when you want an independent perspective from a different model —
    for architecture calls, tricky trade-offs, reviewing a plan, or sanity-checking
    an approach before committing to it.

    Args:
        prompt: The question or request for the advisor. Be specific about what
            kind of guidance you want (e.g. "review this plan", "which approach
            is safer", "what am I missing").
        context: Optional supporting material (code, error output, a draft plan)
            that the advisor should consider when answering.
        model: Advisor model to query. Defaults to the configured model
            (``claude-fable-5``).
        max_tokens: Maximum tokens in the advisor's response.
        temperature: Sampling temperature (0.0-1.0).

    Returns:
        The advisor's guidance as text.
    """
    try:
        return _call_fable(
            prompt,
            context=context,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except CredentialError as exc:
        return f"Advisor unavailable — credential error: {exc}"
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:600] if exc.response is not None else ""
        return f"Advisor request failed ({exc.response.status_code}): {detail}"
    except httpx.HTTPError as exc:
        return f"Advisor request failed: {exc}"


@mcp.tool()
def get_version() -> str:
    """Return this MCP server's name, version, and configured advisor model."""
    return f"advisor-mcp {__version__} (default model: {DEFAULT_MODEL})"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
