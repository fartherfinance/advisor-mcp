# advisor-mcp

A local [MCP](https://modelcontextprotocol.io) server that lets the model you're
running in Claude Code (Opus / Sonnet / Haiku) consult **Fable** (`claude-fable-5`)
for a second opinion or extra guidance.

It **reuses the credential Claude Code already stores locally** — a Max/Pro
subscription OAuth token or an API-key login — so it needs no separate
configuration. Subscription tokens are billed against your Max plan just like
normal Claude Code usage.

## Tools

| Tool | Description |
| --- | --- |
| `ask_advisor` | Ask Fable for guidance. Args: `prompt`, optional `context`, `model`, `max_tokens`, `temperature`. |
| `get_version` | Report the server version and configured advisor model. |

## How it works

The server resolves a credential in this order:

1. `ANTHROPIC_OAUTH_TOKEN` from `.env` (explicit override)
2. `~/.claude/.credentials.json` (Linux OAuth login), or `ADVISOR_CREDENTIALS_PATH`
3. macOS Keychain `Claude Code-credentials` → `claudeAiOauth` (macOS OAuth login)
4. macOS Keychain `Claude Code` (API-key login)

OAuth tokens are sent as `Authorization: Bearer <token>` (with
`anthropic-beta: oauth-2025-04-20`); API keys as `x-api-key`. Either way,
requests present as Claude Code (`anthropic-beta: claude-code-20250219`,
`claude-cli` user agent, and the Claude Code identity line leading the system
prompt) — orgs often cap raw API traffic per model while allowing Claude Code
usage, so this routing is load-bearing. Expired OAuth tokens are refreshed
automatically and written back to their source (file or Keychain) so Claude
Code's copy stays valid.

## Setup

Requires Python 3.13 and [pipenv](https://pipenv.pypa.io/).

```bash
cd /path/to/advisor-mcp
pipenv install
cp .env.example .env   # optional — defaults reuse your Max subscription
```

## Register as a global (user-scope) MCP server

The server is registered in `~/.claude.json` under `mcpServers` so it loads for
**every** project, using absolute paths (no relative paths, no cwd assumptions):

```json
"advisor": {
  "type": "stdio",
  "command": "cmd",
  "args": ["/c", "pipenv", "run", "python", "-m", "advisor_mcp.server"],
  "env": {
    "PIPENV_PIPFILE": "C:\\path\\to\\advisor-mcp\\Pipfile",
    "PYTHONPATH": "C:\\path\\to\\advisor-mcp"
  }
}
```

`PIPENV_PIPFILE` lets pipenv find the project's virtualenv from any working
directory, and `PYTHONPATH` makes the `advisor_mcp` package importable.

## Configuration

All settings are optional and read from `.env` (git-ignored). See `.env.example`
for the full list — `ADVISOR_MODEL`, `ADVISOR_MAX_TOKENS`, `ADVISOR_TIMEOUT`,
`ADVISOR_CREDENTIALS_PATH`, and `ANTHROPIC_OAUTH_TOKEN`.
