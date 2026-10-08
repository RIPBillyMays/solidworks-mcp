# Connecting AI clients to the SOLIDWORKS MCP server

Last updated: 2026-10-08 (Phase 5a). Three clients are registered against the same stdio server:

- Claude Code (CLI), user scope
- Claude Desktop (app)
- Codex CLI

Server executable (all three use it, with no arguments and no environment variables):

```
C:\_Projects\solidworks-mcp\.venv\Scripts\solidworks-mcp.exe
```

The server is stdio only. Each client starts its own copy of the process when it needs it. Nothing listens on a port. The server does not attach to SOLIDWORKS until a tool is called, so registering it, listing tools, or starting a client never touches SOLIDWORKS.

The only tool that is safe to call at any time is `solidworks_status` (read-only: attaches to a running SOLIDWORKS, reports the version and active document; with no session it returns an error message, which still proves the round trip works).

If you move or recreate the `.venv`, re-register all three clients (the path is absolute in each config).

## Before you use it live

Read this before you ask any client to do real work.

- [ ] Launch SOLIDWORKS 2017 yourself and let it finish starting. Dismiss every startup dialog (tips, update prompts, license notices). A modal dialog can hang COM calls.
- [ ] Save and close your own work. Do not have real parts, assemblies or drawings open while an AI is driving.
- [ ] File writes go only to `C:\_Projects\solidworks-mcp\sandbox\` for now (ADR-0005, rule R-007). Create the folder first if it does not exist. Do not point a client at real project files.
- [ ] Know the broken tools. Until Phase 2 lands, some tools fail or misbehave. The list is in `docs/PLAN.md` under "⚠️ Using the clients before Phases 2–4". Do not rely on those tools yet.
- [ ] Be at the keyboard so you can dismiss a dialog if a call hangs.
- [ ] Start with `solidworks_status` ("what SOLIDWORKS version and document are you attached to?") before anything that changes a model.

### About rules and instructions files

- Codex reads `AGENTS.md`. Claude Code reads `CLAUDE.md`. Each file only affects sessions started in this repo (or a folder under it). Claude Desktop reads neither.
- At the time of writing this repo has a `CLAUDE.md` but no `AGENTS.md`, so a Codex session gets none of the repo's written guidance.
- The modeling rules ("the brain") are not yet delivered by the server. The server sends no `instructions` at initialize and exposes no rules resources or prompts. That arrives with Phase 6 (ADR-0004, status Proposed until G6). Until then, any client, including Claude Desktop, only sees the 92 tool descriptions plus whatever you type. State your rules (units in mm, plan before building, sandbox-only paths) in your prompt.

## Claude Code (CLI)

**Config location:** user scope, stored in `C:\Users\<you>\.claude.json` (managed by the CLI; do not hand-edit). User scope means the server is available in every project folder.

**Command used:**

```powershell
claude mcp add --scope user solidworks -- C:\_Projects\solidworks-mcp\.venv\Scripts\solidworks-mcp.exe
```

**Verify:**

```powershell
claude mcp list          # solidworks should be listed
claude mcp get solidworks   # expect: Status: Connected, Type: stdio
```

Inside a session, `/mcp` shows the same status and the tool list. Tool ids are prefixed, for example `mcp__solidworks__solidworks_status`.

Round trip from a shell (read-only; requires being logged in with `claude auth login` first):

```powershell
claude -p "Call the solidworks_status tool from the solidworks MCP server exactly once and report its raw result verbatim. Do not call any other tool." --allowedTools "mcp__solidworks__solidworks_status" --max-turns 3
```

Permissions: by default Claude Code asks before calling an MCP tool. Allow tools one at a time with `--allowedTools` or in settings, rather than allowing the whole server (`mcp__solidworks`) while the Phase 2 bugs are open.

**Disable or remove:**

```powershell
claude mcp remove solidworks -s user
```

To pause it without removing, use `/mcp` inside a session and disable the server for that session.

**Restart needs:** a running Claude Code session does not pick up a newly added server. Start a new session (or restart it) after adding or removing.

**Timeout:** no setting is needed. Claude Code's default MCP tool-call timeout is very long. If you want a cap, set the environment variable `MCP_TOOL_TIMEOUT` (milliseconds, for example `120000`) before launching `claude`. `MCP_TIMEOUT` is the separate startup timeout. (Not exercised in Phase 5a.)

## Claude Desktop (app)

**Config location:** `%APPDATA%\Claude\claude_desktop_config.json` (that is `C:\Users\<you>\AppData\Roaming\Claude\claude_desktop_config.json`).

**Snippet merged in** under the top-level `mcpServers` key (every other key and server was left untouched):

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "C:\\_Projects\\solidworks-mcp\\.venv\\Scripts\\solidworks-mcp.exe",
      "args": []
    }
  }
}
```

JSON needs doubled backslashes in the path, as shown.

**Backup:** the file as it was before the edit is saved next to it as `claude_desktop_config.json.bak-2026-10-08`. Restoring that copy removes the SOLIDWORKS entry, but also reverts any other change Desktop has made to the file since.

**Restart needs:** Claude Desktop only reads this file at startup. **Fully quit the app (right-click the tray icon, Quit; closing the window is not enough) and start it again.** This has not been done as part of Phase 5a. Until you restart, Desktop does not know about the server.

**Verify (after restart):**

- Settings > Developer lists `solidworks` as running (no error badge).
- In a new chat, the tools/connectors menu shows `solidworks` with its tools.
- Ask: "Call solidworks_status and show me the raw result." With SOLIDWORKS closed you should get "No running SOLIDWORKS session is available." That counts as a pass.
- If it fails to start, the MCP log is in `%APPDATA%\Claude\logs\` (look for `mcp-server-solidworks.log`).

**Disable or remove:** delete the `solidworks` entry from `mcpServers` (keep the JSON valid: no trailing comma), then restart Desktop. Or restore the backup file as described above.

**Timeout:** Claude Desktop has no documented per-server timeout setting. Its client-side request timeout (commonly about 60 s) applies, so a slow SOLIDWORKS operation can show as a failed call in Desktop even though SOLIDWORKS is still working. Check SOLIDWORKS before retrying, and prefer Claude Code or Codex for long operations. (Not exercised in Phase 5a.)

## Codex CLI

**Config location:** `C:\Users\<you>\.codex\config.toml` (shared by the CLI and the Codex app). The CLI wrote the first part; the second was added by a small script.

**Command used:**

```powershell
codex mcp add solidworks -- C:\_Projects\solidworks-mcp\.venv\Scripts\solidworks-mcp.exe
```

**Resulting table, after raising the timeout:**

```toml
[mcp_servers.solidworks]
command = 'C:\_Projects\solidworks-mcp\.venv\Scripts\solidworks-mcp.exe'
args = []
tool_timeout_sec = 120
```

**Backup:** `config.toml.bak-2026-10-08` in the same folder, made before any change.

**Timeout:** `tool_timeout_sec = 120` is the per-tool-call limit in seconds for this server. SOLIDWORKS operations (rebuilds, STEP export, opening large files) can be slow, so it is raised to 120 s. `startup_timeout_sec` is the separate startup limit and is left at its default. The key name was checked against the installed Codex binary (v0.159.2) and `codex mcp get solidworks` reports `tool_timeout_sec: 120`.

**Verify:**

```powershell
codex mcp list            # solidworks should appear
codex mcp get solidworks  # shows command and tool_timeout_sec
```

Round trip (read-only):

```powershell
codex exec --skip-git-repo-check --ephemeral "Call the solidworks_status tool from the solidworks MCP server exactly once and report its raw result verbatim. Do not call any other tool."
```

**Disable or remove:**

```powershell
codex mcp remove solidworks
```

To keep the entry but switch it off, add `enabled = false` to the `[mcp_servers.solidworks]` table.

**Restart needs:** each `codex` / `codex exec` run reads the config when it starts, so a new run is enough. A Codex session that is already open needs to be restarted to see the change.

**Heads-up on approvals:** this machine's Codex config has `sandbox_mode = "danger-full-access"`, and non-interactive `codex exec` runs with approval `never`. In the Phase 5a test the MCP call ran without any prompt. That means Codex can call any of the 92 tools without asking you. Do not give Codex open-ended modeling tasks until you are at the keyboard with SOLIDWORKS prepared as in the checklist above. Narrowing this (for example a Codex profile that runs with approvals on) is a decision for you, not changed here.

## Quick reference

| | Claude Code | Claude Desktop | Codex CLI |
|---|---|---|---|
| Config | `~\.claude.json` (user scope) | `%APPDATA%\Claude\claude_desktop_config.json` | `~\.codex\config.toml` |
| Add | `claude mcp add --scope user ...` | merge `mcpServers.solidworks` | `codex mcp add ...` |
| Check | `claude mcp get solidworks` | Settings > Developer | `codex mcp get solidworks` |
| Remove | `claude mcp remove solidworks -s user` | delete the key, restart | `codex mcp remove solidworks` |
| Restart | new session | quit fully and reopen | new run |
| Timeout | `MCP_TOOL_TIMEOUT` (optional) | none to set | `tool_timeout_sec = 120` |
| Repo guidance file | `CLAUDE.md` | none | `AGENTS.md` (not present yet) |
| Backup | none needed | `.bak-2026-10-08` | `.bak-2026-10-08` |
