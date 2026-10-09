# Handoff: 2026-10-08-05 Phase 4 offline done, live T4 next

## Resume prompt (paste into a fresh session)
`Read CLAUDE.md, then docs/handoff/2026-10-08-05-phase4-offline-done.md, then continue from "Next steps".`

## Where we are
- **Phase / gate:** Phase 4. Offline fixes, fences and verification are done. **Next: live 🧪 T4**, then 🧑 G4.
- **Branch:** `phase-4-fix-fence`, from `main` at `a70583c`. **Everything is uncommitted** (commit only with Zach's OK at G4).
- **SOLIDWORKS state:** not touched this session.

## Done this session
- **ADR-0006 (fencing)** written and accepted under G3's approval: `solidworks_mcp/sw2017_fences.py` holds the `FENCES` registry. A one-line hook in `solidworks_mcp/server.py` applies it. Fenced tools stay listed with a `NOT SUPPORTED ON SOLIDWORKS 2017:` prefix. `SW_MCP_DISABLE_FENCES=1` bypasses the fences.
- **Sonnet implementer** (`docs/reports/phase4-implementation.md`):
  - fenced `auto_dimension_view`
  - `chamfer` equal_distance → angle_distance at 45° (`data.substituted`)
  - `rib` retries all 4 direction/material combinations
  - `insert_component` moves the component origin to x/y/z (GetMathUtility, CreateTransform, SetTransformAndSolve2, all in the 2017 snapshot)
  - `export_document`/`save_document` succeed when errors == 0 and this call wrote a non-empty file; warnings go in data
  - the smoke suite closes only the documents it owns and reports `FENCED`
  - 23 new unit tests in `tests/test_sw2017_phase4.py`
- **Separate Sonnet verifier:** PASS on all 9 criteria (`docs/reports/phase4-verification.md`). The orchestrator fixed its 3 low-severity defects, including a hardening fix: a failed `_open_titles` query can no longer mark documents as suite-owned.
- **Evidence:** 97 unit tests OK; `mcp_smoke_client` lists 92 tools.

## Decisions made
- Fencing mechanism → ADR-0006.
- The chamfer substitution is a fix, not a fence (ADR-0006 Context).

## Waiting on Zach
- Before T4: launch SOLIDWORKS 2017, save and close your own documents, and say "ready".

## Next steps (in order)
1. Zach confirms SW is running with no documents of his open.
2. **Live T4, one Sonnet subagent, serial** (Zach's request: Sonnet drives every live MCP/SW interaction, to save orchestrator tokens):
   - Run `tests/live_sw2017_smoke.py` with `SW_MCP_OUTPUT_ROOT=<repo>\sandbox`.
   - Report in ≤150 words; write the matrix to `docs/reports/phase4-live-matrix.md`.
   - Pass criterion: every tool is PASS or FENCED. The section-view depth check is still UNVERIFIED (TODO in the script); decide at G4 whether that's acceptable.
   - Watch for `insert_component`: SetTransformAndSolve2 may not move a *fixed* first component (`data.warning`).
3. Fix any T4 failures (offline implementer, then verifier, then a live re-test of that tool only).
4. 🧑 G4: present the fenced list (`auto_dimension_view`) and the substitution (chamfer), and ask to commit, merge and push.

## Gotchas learned
- The 3.1 regression (`tests/live_p0_regression.py`) leaves 3 unsaved parts open. Those are test documents, not Zach's.
- The Phase 2 carry-overs (delete_feature `DeleteSelection2(0)`, bare except around ViewZoomtofit2, `ISheet.GetSize`, `IMate2` Distance/Angle) are still open. They're out of Phase 4 scope unless T4 shows them failing.

## Key files
- `docs/adr/0006-sw2017-tool-fencing.md`, `solidworks_mcp/sw2017_fences.py`
- `docs/reports/phase4-implementation.md`, `docs/reports/phase4-verification.md`
- `tests/test_sw2017_phase4.py`, `tests/live_sw2017_smoke.py`
