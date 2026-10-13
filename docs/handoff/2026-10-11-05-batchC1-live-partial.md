# Handoff: 2026-10-11-05 Batch C1 live partial; SOLIDWORKS crashed on the cam mate

## Resume prompt (paste into a fresh session)
`Read CLAUDE.md, then docs/handoff/2026-10-11-05-batchC1-live-partial.md, then continue from "Next steps".`

## Where we are
- **Phase / gate:** Phase 5, Batch C live passes (C2 ✅, C3 ✅, C1 partial), then 5.4 guided session, then 🧑 G5.
- **Branch:** `phase-5-clients-guided`, all uncommitted.
- **SOLIDWORKS state:** **crashed** (AddMate5 for a cam mate → RPC failed; process gone). Zach must relaunch it.

## Done
- Report: `docs/reports/phase5-batchC1-live.md` (includes the agent's resume plan).
- PASS: limit_distance, limit_angle (but the drag-past-limit check is weak: move_component didn't move the block).
- Built but behavior unproven: gear (type 10; 3:2 ratio reads back swapped), screw (type 17). Driving one part never moved its partner.
- rack_pinion: AddMate5 "unknown error" with the distance slot; try the ratio slot once, else per-type refusal.
- cam: per-type refusal added in `add_mate` (`fenced=True`, before COM), with a unit test. Unit tests 479 OK.
- Files changed: `sw_mates_adv.py`, `sw_assembly.py`, `tests/test_sw2017_batchC_assembly.py`.

## Next steps (in order)
1. Zach relaunches SW 2017, no docs open.
2. Resume C1 **one stage per agent run** (a crash loses the whole run): rack_pinion ratio slot; then hinge/slot/path/symmetric/width; then add_mate_reference; then the three component patterns + mirror; then sub-assembly. Append results to the C1 report.
3. Decide gear/screw: keep with a "behavior unverified" note, or re-test motion another way (e.g. rotate via rotate_component + read partner transform after rebuild).
4. Orchestrator applies any whole-tool fences, writes the handoff, then the 5.4 guided session, then 🧑 G5.

## Gotchas
- The cam mate crashes SOLIDWORKS 2017; never re-probe it live.

## Update: stage 1 resume (same day)
- SW crashed again, this time on the **path** mate (AddMate5). Never re-probe path live.
- Per-type refused (`UNSUPPORTED_MATE_TYPES` in `sw_mates_adv.py`, with unit tests): cam, rack_pinion, hinge, path. Unit tests 482 OK.
- slot: builds (type 21) in all four modes; constraint positions unverified.
- Still to run: symmetric, width, the gear/screw motion check, add_mate_reference, component patterns + mirror, sub-assembly. One stage per run.
