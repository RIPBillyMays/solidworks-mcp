# Handoff: 2026-10-10-01 Phase 5, T5 (Claude Code) geometry passed, save pending MCP restart

## Resume prompt (paste into a fresh session)
`Read CLAUDE.md, then docs/handoff/2026-10-10-01-phase5-t5-restart.md, then continue from "Next steps".`

## Where we are
- **Phase / gate:** Phase 5 in progress (🧪 T5 partial, 🧑 G5 not reached).
- **Branch:** `phase-5-clients-guided` (from `main` at `9b07484`). Uncommitted: `docs/reports/phase5-t5-claudecode.md`, `rules/candidates.md` (R-010, R-011 proposed), this handoff. Commit only with Zach's OK.
- **SOLIDWORKS state:** running. `Part1` (block + Ø10 hole, built by the Sonnet driver) is **open, dirty, unsaved**. Do not close it until saved.

## Done
- Sonnet driver built the block via `mcp__solidworks__*` only (17 calls, no retries). Measured: volume 14214.6018 mm³, bbox 50×30×10 (min -25,-15,0), 1 body, 0 rebuild errors, hole r=5 through, COM at x=0,y=0. Report: `docs/reports/phase5-t5-claudecode.md`.
- Save was refused: `OUTPUT_ROOT` defaulted to `~\Documents\solidworks-mcp` because the Claude Code registration had no `SW_MCP_OUTPUT_ROOT`.
- Zach chose Option A. Claude Code registration redone (user scope) with `SW_MCP_OUTPUT_ROOT=C:\_Projects\solidworks-mcp\sandbox` (`claude mcp get solidworks` confirms). `sandbox\phase5\` creation was not confirmed; create it if missing.
- Rule candidates R-010 (check `output_root` first) and R-011 (re-list faces before each selection) added as `proposed`.

## Blocked / needs Zach
- **Claude Desktop config:** `%APPDATA%\Claude\claude_desktop_config.json` currently has **no `mcpServers` key** (the Phase 5a entry is gone; the app likely rewrote the file). An attempt to re-add it with the sandbox env var was denied by the auto-mode classifier, so it was not changed. A backup `claude_desktop_config.json.bak-2026-10-10` exists (identical to current). Zach should add it, or approve the edit. Entry to add:
  `"mcpServers": {"solidworks": {"command": "C:\\_Projects\\solidworks-mcp\\.venv\\Scripts\\solidworks-mcp.exe", "args": [], "env": {"SW_MCP_OUTPUT_ROOT": "C:\\_Projects\\solidworks-mcp\\sandbox"}}}` then restart Claude Desktop. Codex is parked.

## Next steps (in order)
1. Restart the Claude Code session so the new MCP env applies. In the new session, `solidworks_status` must report `output_root` = `...\sandbox`.
2. Sonnet driver, serial: save `Part1` to `C:\_Projects\solidworks-mcp\sandbox\phase5\t5_claudecode_block.SLDPRT` via `save_document`; verify the file exists and is non-empty; re-measure volume. Update the report to PASS. Then close only `Part1`.
3. Zach does the Claude Desktop T5 run (same prompt: "50×30×10 mm block with a Ø10 mm through-hole, centered"; expected volume ≈ 14214.6 mm³) once the Desktop config is fixed.
4. 5.4 guided session: Zach asks for a simple part, orchestrator narrates each tool call and the COM call underneath (`docs/how-it-works.md`), Sonnet drives.
5. 🧑 G5: hands-on review, confirm R-010/R-011, harvest more candidates. Update the PLAN status table. Handoff.

## Gotchas learned
- `claude mcp add` is variadic on `-e`: put the server name first, then `-e KEY=VAL`, then `--` and the command. The wrong order fails with "missing required argument 'commandOrUrl'" **after** `mcp remove` has already run.
- Face indices and body names shift after each feature; the body is renamed after a cut.
- The Front Plane extrudes along +Z. `list_faces` reports `normal` and `surface_normal` with opposite signs.

## Key files
- `docs/reports/phase5-t5-claudecode.md`
- `docs/clients.md` (still says "no environment variables"; update it after the Desktop fix)
- `rules/candidates.md`
