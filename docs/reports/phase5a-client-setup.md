# Phase 5a: client registration and T5a round trip

Date: 2026-10-08
Target: SOLIDWORKS 2017 (**not running** during these checks; `Get-Process SLDWORKS` returned nothing before and during the tests)
Server: `C:\_Projects\solidworks-mcp\.venv\Scripts\solidworks-mcp.exe` (92 tools, stdio)
Only tool called anywhere: `solidworks_status` (read-only).

How each client is set up, verified, and removed is in `docs/clients.md`.

## Registrations

| Client | Method | Result |
|---|---|---|
| Claude Code 2.1.258 | `claude mcp add --scope user solidworks -- <exe>`; no pre-existing `solidworks` entry | PASS: `claude mcp get solidworks` reports `Status: Connected`, Type stdio |
| Claude Desktop | merged `mcpServers.solidworks` into `%APPDATA%\Claude\claude_desktop_config.json` with a script | PASS (file level): JSON re-parsed, all original keys and servers value-identical. Server list before: none. After: `solidworks`. **Not yet loaded by the app: restart needed.** |
| Codex CLI 0.159.2 | `codex mcp add solidworks -- <exe>`, then `tool_timeout_sec = 120` and `args = []` added to the table | PASS: `codex mcp get solidworks` shows `enabled: true`, `tool_timeout_sec: 120` |

Backups (made before any change):

- `C:\Users\Zach Tonsmeire\AppData\Roaming\Claude\claude_desktop_config.json.bak-2026-10-08`
- `C:\Users\Zach Tonsmeire\.codex\config.toml.bak-2026-10-08`
- Claude Code: configured through the CLI (`~\.claude.json`), no manual edit, no backup file.

Codex timeout key: `tool_timeout_sec` (confirmed present in the Codex v0.159.2 binary alongside `startup_timeout_sec`; the CLI echoes it back).

## T5a: round trip, `solidworks_status`

SOLIDWORKS running: **no**. Prompt used for both clients:

> Call the solidworks_status tool from the solidworks MCP server exactly once and report its raw result verbatim. Do not call any other tool.

### Codex CLI: PASS

Command: `codex exec --skip-git-repo-check --ephemeral "<prompt>"` (first attempt; no approval flags needed, no bypass flags used).

Trace (trimmed):

```
mcp: solidworks/solidworks_status started
mcp: solidworks/solidworks_status (completed)
{"content":[{"type":"text","text":"{\n  \"ok\": false,\n  \"message\": \"No running SOLIDWORKS session is available. Open SOLIDWORKS and finish any modal dialogs first.\"\n}"}],"isError":false}
```

The client called the server's tool and returned its response. The "no running session" message counts as PASS per the T5a definition.

Note: the run was non-interactive and the MCP call was not gated by an approval prompt (user config has `sandbox_mode = "danger-full-access"`). See the approvals heads-up in `docs/clients.md`.

### Claude Code: NOT RUN (blocked by authentication, not by the server)

Command: `claude -p "<prompt>" --allowedTools "mcp__solidworks__solidworks_status" --max-turns 3`

Result:

```
Failed to authenticate: OAuth session expired and could not be refreshed
```

`claude auth status` returned `"loggedIn": false` in the shell used for this task. The failure happens before any model or tool call, so it says nothing about the server. Logging in is a credential step and was not attempted. Repeating the command after `claude auth login` in your own terminal completes this check.

What was verified for Claude Code without the model:

- `claude mcp get solidworks` -> `Status: Connected` (Claude Code started the server over stdio and completed the MCP handshake).

Supplemental server-side evidence (not a substitute for the client round trip): a throwaway stdio script spoke raw MCP to the same executable, calling only `solidworks_status`:

```
server: {'name': 'solidworks-mcp', 'version': '1.30.0'}
{"content": [{"type": "text", "text": "{\n  \"ok\": false,\n  \"message\": \"No running SOLIDWORKS session is available. Open SOLIDWORKS and finish any modal dialogs first.\"\n}"}], "isError": false}
```

(`1.30.0` is the `mcp` library version, as noted in the Phase 1 report.)

### Claude Desktop: NOT RUN

Desktop only reads its config at startup, and restarting the app was out of scope. Round trip pending Zach's restart. Verification steps are in `docs/clients.md`.

## Summary

| Client | Registered | T5a round trip |
|---|---|---|
| Claude Code | PASS (Connected) | NOT RUN: CLI not logged in; `claude mcp get` handshake OK |
| Claude Desktop | PASS (config merged, JSON valid) | NOT RUN: restart app first |
| Codex CLI | PASS | **PASS** |

## Open items for Zach

1. Run `claude auth login` (or `/login` in an interactive `claude`), then re-run the Claude Code T5a command above.
2. Fully quit and restart Claude Desktop, then ask it to call `solidworks_status` (a "No running SOLIDWORKS session" reply is a pass).
3. Decide whether Codex should keep approval-free tool calls (see `docs/clients.md`).
4. Optional: add an `AGENTS.md` so Codex gets repo guidance; none exists yet.
