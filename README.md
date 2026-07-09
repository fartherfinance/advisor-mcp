# advisor-mcp

A local [MCP](https://modelcontextprotocol.io) server that lets the model you're
running in Claude Code (Opus / Sonnet / Haiku) consult **Fable** (`claude-fable-5`)
for a second opinion or extra guidance.

It **reuses your existing Claude Max subscription** — the OAuth token that Claude
Code already stores in `~/.claude/.credentials.json` — so it needs **no separate
paid API key**. Requests are billed against your Max plan just like normal Claude
Code usage.

## Tools

| Tool | Description |
| --- | --- |
| `ask_advisor` | Ask Fable for guidance. Args: `prompt`, optional `context`, `model`, `max_tokens`, `temperature`. |
| `get_version` | Report the server version and configured advisor model. |

## How it works

The server reads the subscription OAuth token from your Claude Code credentials
file and calls the Anthropic Messages API with:

- `Authorization: Bearer <token>` (not an API key)
- `anthropic-beta: oauth-2025-04-20`
- a system prompt that begins with the Claude Code identity line

If the token has expired it is refreshed automatically using the stored refresh
token and written back to the credentials file. You can override the credential
source (or point to an explicit token) via `.env` — see `.env.example`.

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
