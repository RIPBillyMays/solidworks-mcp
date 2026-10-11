# Handoff: 2026-10-11-02 Batch C offline done; next is the live pass C2

## Resume prompt
`Read CLAUDE.md, then docs/handoff/2026-10-11-02-batchC-offline-done.md, then continue from "Next steps".`

## Where we are
- **Gate:** G-C0 approved 2026-10-11 (D1–D6 as recommended; ADR-0007 Accepted).
- **Branch:** `phase-5-clients-guided`, all uncommitted (commit only with Zach's OK).
- **Offline state:** 479 unit tests OK; the smoke client lists 168 tools (was 146). `sw2017_fences.py` unchanged.
- **Verification:** an independent verifier plus a fixer ran. See `docs/reports/phase5-batchC-offline-verify.md`; its "Fixes applied" section is at the end. Low items #7–10 and #12 are deferred to the live pass.
- **Claude Desktop T5:** still waiting on Zach to run `tools/compat/register_claude_desktop.ps1` with Desktop quit (steps in `docs/clients.md`).

## Key files
- **Plan:** `docs/plans/phase5-batchC-plan.md`, including the "C0 results" amendments.
- **Typelib probe:** `docs/reports/phase5-batchC-typelib-probe.md`.
- **Offline reports:** `docs/reports/phase5-batchC{1,2,3}-offline.md`. Each lists its LIVE-PROBE constants: guessed selection marks and argument values.
- **Live scripts (never run yet):** `tests/live_p5_batchC{1,2,3}.py`. Each aborts unless the output root is `sandbox`.

## Next steps
1. Zach saves and closes his SOLIDWORKS work. SW stays running.
2. Live pass **C2** (one Sonnet agent, serial):
   - Run `live_p5_batchC2.py`, item by item.
   - Probe the LIVE-PROBE constants first. Stop at the first modal dialog.
   - Fix or fence each item, with at most 2 attempts per item.
   - Write `docs/reports/phase5-batchC2-live.md`.
   - The orchestrator applies the fences.
3. Write a handoff, then live pass C3, then C1. Decide per-type refusal for hinge/path mates in `plan_advanced_mate` if they fail; a whole-tool fence can't cover a mate type.
4. Then the 5.4 guided session, then 🧑 G5.
