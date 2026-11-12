🚨 **CRITICAL FINDINGS ONLY** — Advisor MCP Server Review

This repo is a small local MCP stdio server (`advisor_mcp/`, Python) that exposes two
tools — `ask_advisor` (queries the Anthropic API as model `claude-fable-5-1`) and
`get_version` — reusing the credential Claude Code already stores locally. Skip any
section below that does not match the changed files; this is a single Python package
with no CI, no tests, and no build pipeline.

**🎯 ONLY REPORT CRITICAL, HIGH & MEDIUM SEVERITY ISSUES:**

**🔴 CRITICAL (Report immediately):**
- Security vulnerabilities — hardcoded secrets, or tokens/credentials logged or
  returned in responses (OAuth access tokens, refresh tokens, API keys from any
  source)
- Credential-file hygiene — `.env`, `~/.claude/.credentials.json` contents, or any
  real token/key value committed to the repo or echoed into an MCP tool response
- Breaking the credential resolution order in `advisor_mcp/credentials.py` (env
  `ANTHROPIC_OAUTH_TOKEN` → `~/.claude/.credentials.json` /
  `ADVISOR_CREDENTIALS_PATH` → macOS Keychain OAuth `Claude Code-credentials` /
  `claudeAiOauth` → macOS Keychain API key `Claude Code`) — a regression breaks
  Claude Code's own login on the user's machine
- Breaking the OAuth refresh write-back: Anthropic OAuth refresh tokens rotate on
  every use, so a refresh that does NOT write the new token back to its source
  (credentials file or Keychain) invalidates the stored credential and logs the
  user out of Claude Code
- Breaking the Claude-Code presentation in `advisor_mcp/server.py` — the
  `anthropic-beta` headers (`oauth-2025-04-20`, `claude-code-20250219`), the
  `claude-cli/...` user agent, and the Claude Code identity line leading the
  system prompt are load-bearing for auth/rate-limit routing; removing or
  reordering them breaks authentication

**🟠 HIGH (Report if found):**
- Silent behavioral regressions in the MCP tools — `ask_advisor` or `get_version`
  in `advisor_mcp/server.py` changing request shape, auth header selection
  (OAuth `Authorization: Bearer` vs `x-api-key`), or response content without the
  change being deliberate
- Breaking the README's setup/run contract (run via
  `python -m advisor_mcp.server` / pipenv, `.env` loading from the project root)
- Inert additions — code or config that is added but can never run
- Anything that corrupts the stdio MCP transport (see Python concerns below)

**🟡 MEDIUM (Report if found):**
- Documentation the diff renders factually wrong: a changed behavior, default,
  flag, env var, command, file role or contract that existing docs (`README.md`,
  `.env.example`, docstrings in `advisor_mcp/*.py`) still describe the old way,
  and the change does not update them. Report only where the diff makes existing
  text false, and quote the stale line. A suggestion to add or improve docs is
  NOT this bullet and stays suppressed.
- A swallowed credential failure in `credentials.py` that reports success or a
  valid credential when resolution or refresh actually failed.

**🐍 PYTHON CONCERNS — apply when `advisor_mcp/*.py` files change:**
- Credential resolution order and error message correctness in
  `credentials.py` — the "No Claude credential found" message must stay accurate
  about which sources were checked
- Refresh-token rotation write-back: the file path must write the exchanged
  token back to the credentials file, and the Keychain path must upsert via
  `security add-generic-password -U`
- Claude-Code impersonation headers, user agent, and identity line in
  `server.py` must stay intact and leading the request/system prompt
- Stdio MCP protocol handling — anything written to stdout that is not valid
  MCP protocol output corrupts the stdio transport; logs must go to stderr,
  never stdout

**❌ DO NOT REPORT (Suppress these):**
- Code style preferences, formatting, naming conventions, type annotations
- The `CLIENT_ID` and `TOKEN_URL` constants in `advisor_mcp/credentials.py` —
  they are documented as intentionally public (shipped in the Claude Code
  client), not secrets
- Non-critical logging or monitoring suggestions
- Documentation improvements offered as suggestions (missing docs, prose
  polish); documentation the diff makes false is reportable as MEDIUM above
- Test/lint/CI additions suggested as improvements — this repo intentionally
  has none

FOCUS ONLY ON ISSUES THAT MATTER. An empty review is a valid review.
