# Handoff: 2026-10-11-03 Batch C2 live done; next is live pass C3

## Resume prompt (paste into a fresh session)
`Read CLAUDE.md, then docs/handoff/2026-10-11-03-batchC2-live-done.md, then continue from "Next steps".`

## Where we are
- **Phase / gate:** Phase 5, Batch C live passes (C2 ✅; C3, C1 to go), then 5.4 guided session, then 🧑 G5.
- **Branch:** `phase-5-clients-guided`, all uncommitted (commit only with Zach's OK).
- **SOLIDWORKS state:** running, no probe documents left open; no preferences changed.

## Done this session
- Live C2 (Sonnet agent): report `docs/reports/phase5-batchC2-live.md`. No modal dialog.
  - PASS: edge flange, hem, fold/unfold, flat-pattern DXF.
  - FIXED: `sheet_metal_base_flange` (Merge/UseFeatScope/UseAutoSelect = False), `swept_thread` (no overshoot on cuts; within 0.2 % of analytic volume), `hole_wizard` cosmetic thread (size `M6x1.0`, 0.5 mm edge tolerance).
  - Fenced (orchestrator): `sheet_metal_sketched_bend` in `sw2017_fences.py`; `fillet_variant type=full_round` as a per-type refusal in `sw_feature.py` (no COM calls). `_full_round_fillet` is left in place, unreachable, for a future re-probe.
- Unit tests: 478 OK (two full-round route tests replaced by one refusal test). Smoke: 168 tools.

## Not finished
- Boss-mode swept threads not tested live (only cut threads). Cover them in C3 or the guided session.

## Waiting on Zach
- Claude Desktop T5: quit Desktop, run `tools/compat/register_claude_desktop.ps1` (`docs/clients.md`).

## Next steps (in order)
1. Confirm Zach's SW work is still closed.
2. Live pass **C3** (one Sonnet agent, serial; same brief shape as C2): `tests/live_p5_batchC3.py`, LIVE-PROBE constants first, ≤2 attempts per item, report `docs/reports/phase5-batchC3-live.md`. Orchestrator applies fences.
3. Handoff, then live pass C1. Per-type refusal for hinge/path mates in `plan_advanced_mate` if they fail (same pattern as full_round).
4. 5.4 guided session, then 🧑 G5.

## Gotchas learned
- Adding a FENCES entry breaks `tests/test_sw2017_phase4.py` unless the fake tool list in `FenceTests.setUp` gets the new name too.
- A sub-mode of a tool that can't work is refused inside the handler with `fenced=True`, not via FENCES.
