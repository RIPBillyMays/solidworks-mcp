# Handoff: 2026-10-11-04 Batch C3 live done; next is live pass C1

## Resume prompt (paste into a fresh session)
`Read CLAUDE.md, then docs/handoff/2026-10-11-04-batchC3-live-done.md, then continue from "Next steps".`

## Where we are
- **Phase / gate:** Phase 5, Batch C live passes (C2 ✅, C3 ✅; C1 to go), then 5.4 guided session, then 🧑 G5.
- **Branch:** `phase-5-clients-guided`, all uncommitted (commit only with Zach's OK).
- **SOLIDWORKS state:** running, no documents open, no preferences changed.

## Done this session
- Live C3 (report `docs/reports/phase5-batchC3-live.md`; the first attempt was interrupted when the app quit, then resumed). No modal dialog.
  - PASS: surface extrude/revolve/loft/offset/knit (incl. form-solid)/thicken, replace_face, split_body method=cut, boss swept_thread (+97.9 vs 97.8 mm³ analytic).
  - FIXED: `edit_feature`: `GetDefinition` is a property on 2017; it is now read via `value()` in `sw_core.feature_data` and `sw_edit.py`. All six types verified by measurement.
  - Fenced (orchestrator): `surface_trim` in `sw2017_fences.py`.
  - `thicken` side=both applies the thickness to each side; the tool description now says so.
- Unit tests: 478 OK. Smoke: 168 tools.

## Waiting on Zach
- Claude Desktop T5: quit Desktop, run `tools/compat/register_claude_desktop.ps1` (`docs/clients.md`).

## Next steps (in order)
1. Confirm Zach's SW work is still closed.
2. Live pass **C1** (one Sonnet agent, serial; same brief shape as C2/C3): `tests/live_p5_batchC1.py`, report `docs/reports/phase5-batchC1-live.md`. If hinge or path mates fail, recommend a per-type refusal in `plan_advanced_mate` (`fenced=True` in the handler), not a whole-tool fence. Orchestrator applies fences.
3. Write the handoff, then the 5.4 guided session, then 🧑 G5.

## Gotchas learned
- A new FENCES entry also needs the fake tool list in `tests/test_sw2017_phase4.py` `FenceTests.setUp`, and any "not fenced" assertions in the batch tests updated.
- If the app quits mid-agent, check file mtimes and `sandbox/probe/` before re-briefing; pass the partial state to the new agent.
