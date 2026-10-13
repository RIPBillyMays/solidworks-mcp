# Handoff: 2026-10-11-06 Batch C live passes done; next is the 5.4 guided session

## Resume prompt (paste into a fresh session)
`Read CLAUDE.md, then docs/handoff/2026-10-11-06-batchC-live-done.md, then continue from "Next steps".`

## Where we are
- **Phase / gate:** Phase 5. Batch C live passes C2 ✅, C3 ✅, C1 ✅. Next: 5.4 guided session, then 🧑 G5.
- **Branch:** `phase-5-clients-guided`, all Batch C work uncommitted (commit only with Zach's OK, at G5 or earlier if he asks).
- **SOLIDWORKS state:** running (relaunched by Zach after two crashes), no docs open.

## Batch C live results (reports: `docs/reports/phase5-batchC{1,2,3}-live.md`)
- **Whole-tool fences added** (`sw2017_fences.py`): sheet_metal_sketched_bend, surface_trim, linear_component_pattern, circular_component_pattern.
- **Per-mode refusals** (fenced=True in handler): fillet_variant full_round; add_mate cam/path/rack_pinion/hinge; create_subassembly virtual.
- **Crash hazards:** cam and path mates kill SOLIDWORKS 2017 via AddMate5. Never re-probe live.
- **Caveats:** gear/screw mates build but motion coupling is unverifiable via API; slot mate position unverified; limit mates' drag-past-limit test weak (move_component didn't move the block — worth a look); thicken "both" doubles thickness.
- Unit tests 482 OK; smoke 168 tools.

## Waiting on Zach
- Claude Desktop T5: quit Desktop, run `tools/compat/register_claude_desktop.ps1` (`docs/clients.md`).
- Whether to commit Batch C now (recommended: yes, one commit "Phase 5 Batch C live-verified").

## Next steps (in order)
1. Commit Batch C if Zach OKs.
2. ✅ move_component checked: expected solver behavior (limit mates snap back); reporting improved, uncommitted. See `docs/reports/phase5-move-component.md`.
3. 5.4 guided session per `docs/PLAN.md`, then 🧑 G5.

## Gotchas
- Live C1 must run one small stage per agent; a SW crash kills the whole run.
- New FENCES entries need the fake tool list in `tests/test_sw2017_phase4.py` updated.
