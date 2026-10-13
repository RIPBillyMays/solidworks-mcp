# Handoff: 2026-10-13-01 Field findings fixed; restart the MCP server, smoke-test, then 🧑 G5

## Resume prompt (paste into a fresh session)
`Read CLAUDE.md, then docs/handoff/2026-10-13-01-field-fixes-done-g5-next.md, then continue from "Next steps".`

## Before starting the new session (Zach)
Restart the SOLIDWORKS MCP server so it loads the new code. The server in any session started before 2026-10-13 runs pre-fix code.
- **Claude Code:** start a fresh session. The server starts with it, or use `/mcp` to reconnect `solidworks`.
- **Claude Desktop:** quit it fully from the tray, then reopen it.
- **SOLIDWORKS:** keep it running with no documents open. Save and close your own work first.

## Where we are
- **Phase / gate:** Phase 5. All fix work is done. Next comes 🧑 G5.
- **Branch:** `phase-5-clients-guided`. The working tree is clean, apart from this file.
- **Commits from these sessions:**
  - `5a04102`: fixes #1 and #3
  - `3e04c41`: batch 2 (#5, #7–#15, #17–#19, #21)
  - `709115a`: #16 loft, plus the Phase 7 triage
- **Not merged** to `main` yet. That waits for Zach at G5.
- **SOLIDWORKS:** running, no documents open, no preferences changed.

## Done (evidence in `docs/reports/`)
The field findings come from `docs/handoff/2026-10-12-01-mcp-field-findings.md`.

| # | Result | Evidence |
|---|---|---|
| 1 | Fixed. Draw tools run with AddToDB on and read back their geometry; mismatches return `ok:false`. New `draw_polyline`. `draw_polygon` `inscribed` now works. | `phase5-fix1-live.md`, `phase5-fix-revisions-live.md` |
| 2 | A symptom of #1. Parallel calls are exact. | `phase5-field-findings.md` |
| 3 | `active_document` appears in every result. New `activate_document`. The field flipping was probably a second client driving SW. | `phase5-fix-revisions-live.md` |
| 4, 6, 8 | Not reproduced; parked in Phase 7. #8 was hardened anyway: delete_feature now clears the selection first. | `phase5-field-findings.md` |
| 5 | New `direction: +normal/-normal`, with the same meaning for boss and cut. Results add `direction_vector` and `volume_delta_mm3`. | `phase5-fixes-live.md` |
| 7, 9, 11, 12, 15 | Fixed and passed live. | `phase5-fixes-live.md` |
| 10 | Warnings split out and `force_all` fixed. The error/warning split is still not verified live; it is in Phase 7. | `phase5-fixes-live-r2.md` |
| 13 | `add_dimension anchor` uses a temporary Fixed relation, matched by type and coordinates. | `phase5-fixes-live-r2.md` |
| 14 | Undo can't remove draw_* geometry, because AddToDB bypasses the undo stack (Zach chose option A). New `delete_sketch_segment`; `undo` hints at it. | `phase5-fixes-live-r2.md` |
| 16 | Root cause: profiles were picked at (0,0,0), so their start points mismatched. Now the picks auto-align. New `start_points`, null hints, and a twist warning. | `phase5-loft-investigation.md`, `phase5-loft-fix-live.md` |
| 17 | Multi-edge variable fillets are refused clearly. `propagate=false` is confirmed live not to propagate. | `phase5-fixes-live.md` |
| 18, 19, 21 | `list_faces`/`list_edges` get limit and filters; `capture_screenshot` gets `save_as`; the output-root docs are in `docs/clients.md`. | `phase5-fixes-live.md` |

- **Offline:** 655 unit tests OK. The smoke client lists 171 tools.
- **Rulebook:** candidates R-012 to R-018 were added to `rules/candidates.md` as *proposed*.
- **Phase 7:** leftovers are triaged in `docs/PLAN.md` under Phase 7.

## Waiting on Zach (🧑 G5)
1. **Guided session:** count the 2026-10-12 field use as the guided session (PLAN 5.4). *Recommend: yes.*
2. **Rule candidates R-012 to R-018:** approve or reject each one. *Recommend approving all of them as soft rules. R-013 (verify by measurement) is a hard-gate candidate later.*
3. **Merge:** merge `phase-5-clients-guided` into `main` after the smoke check below passes. *Recommend: yes.*

## Next steps (in order)
1. Check that the restarted server runs the new code: `mcp__solidworks__solidworks_status` shows `output_root` = `C:\_Projects\solidworks-mcp\sandbox`, and the tool list includes `draw_polyline`, `activate_document` and `delete_sketch_segment`.
2. Brief one Sonnet agent for an **MCP-level smoke run** through the real `mcp__solidworks__*` tools. This is the first time the fixes run through the restarted server; until now every live test called `server.call_tool` directly. Keep it short:
   - **Part:** a new part in `sandbox/`.
   - **Base:** a `draw_polyline` star, then `boss_extrude direction=+normal`. Check the volume against the shoelace area × depth.
   - **Loft:** the 240×70 R16 → 234.4×70 R16 loft. Expect about 45876 mm³.
   - **Sketch edits:** `sketch_fillet` by corners, then `delete_sketch_segment`.
   - **Documents:** `activate_document` between two parts.
   - **Cleanup:** close everything.
   - Write the results to `docs/reports/phase5-mcp-smoke-postfix.md`.
3. Present 🧑 G5 to Zach: what was done, the evidence (the table above plus the smoke report), and the three decisions above.
4. After G5:
   - Merge to `main` with Zach's OK.
   - Update the PLAN status table: Phase 5 ✅, Phase 6 next.
   - Move the approved rules to active in `rules/` and log them in `rules/CHANGELOG.md`.

## Gotchas learned
- **MCP server code age:** a session's MCP server runs the code it was started with. To test new code mid-session, call `solidworks_mcp.server.call_tool` from a script (see `tests/live_p5_fix3_activedoc.py`) with `SW_MCP_OUTPUT_ROOT` set.
- **Arcs on 2017:** sketch arcs keep the requested start/end order, so a clockwise arc reports `GetRotationDir=-1`. Any arc maths must read `GetRotationDir`. This bit us twice, in `delete_sketch_segment` and in the loft area estimate.
- **COM identity:** `==` works for some CDispatch objects (sketches), but not for freshly fetched relation wrappers. Match by type and coordinates instead.
- **Selection:** `SelectByID2` returns True even for picks far off the target, so validate pick points yourself.
- **AddToDB:** geometry created this way is not undoable. Use `delete_sketch_segment`.
- **Live batches:** a big live batch in one agent took about 100 minutes. Split live work into one agent per script.
- **Other clients:** another client or session may be driving SOLIDWORKS (the `ESP32-C3 SuperMini.SLDPRT` episode). Probes must list open documents first and stop on anything foreign.

## Key files
- `docs/PLAN.md`: status table and the Phase 7 list
- `docs/FORK_CHANGES.md`
- `rules/candidates.md`: R-012 to R-018
- `docs/reports/phase5-*`
- live scripts: `tests/live_p5_fix*.py`, `tests/live_p5_fixes_*.py`, `tests/live_p5_loft_*.py`
