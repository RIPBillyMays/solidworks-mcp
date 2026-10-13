# Handoff: 2026-10-12-02 Field fixes batch 2 (#5, #7–#15, #17–#19, #21): live-tested, 3 bugs open

## Resume prompt
`Read CLAUDE.md, then docs/handoff/2026-10-12-02-field-fixes-batch2.md, then continue from "Next steps".`

## Where we are
- **Branch:** `phase-5-clients-guided`.
- **Last commit:** `5a04102` covers fixes #1 (exact sketch geometry, `draw_polyline`) and #3 (`active_document` in results, `activate_document`). Zach approved it.
- **Uncommitted (batch 2):** these changes are verified offline and live-tested.

| Area | Findings | Code | Tests |
|---|---|---|---|
| Features | #5, #8, #9, #17 | `sw_feature.py` | `tests/test_sw2017_feature_fixes.py` |
| Sketch | #7, #11–#15 | `sw_sketch.py`, `sw_select.py`, `sw_core.py` | `tests/test_sw2017_sketch_edit_fixes.py` |
| File/inspect | #10, #18, #19, #21 | `sw_file.py`, `sw_inspect.py`, `sw_core.py`, `docs/clients.md` | `tests/test_sw2017_file_inspect_fixes.py` |

- **Also uncommitted:**
  - `docs/FORK_CHANGES.md` entries for all 3 groups
  - `rules/candidates.md` R-012 to R-018 (proposed)
  - reports in `docs/reports/phase5-fixes-*.md`
  - the live scripts `tests/live_p5_fixes_{feature,sketch,file_inspect}.py`
- **PLAN.md:** #4, #6 and #8 are parked in Phase 7 as "not reproduced" (committed). #8 got the clear-selection hardening anyway.
- **Offline suite:** 619 tests OK.
- **SOLIDWORKS:** running, no documents open.

## Live result (`docs/reports/phase5-fixes-live.md`)
52 PASS, 8 FAIL, 1 SKIP.
- **Passed live:**
  - #5 direction on Front, Top and Right
  - #8, #9, #11, #12, #15
  - #18 (231-face part, feature filter OK)
  - #19
- **#17:** `propagate=false` does NOT propagate on 2017 (volume and face evidence). This is documented.
- **Skipped:** the #10 error/warning split, because no rebuild error could be provoked.

## Open bugs (the 8 FAILs; fix offline, then re-run the live scripts)
1. **#13 `add_dimension` anchor** (`sw_sketch.py` `_temporary_fixed`):
   - The identity check at ~l.1519 (`==`) fails on fresh relation wrappers, so the temporary Fixed relation leaks.
     - Suggested fix: identify the new relation by diffing relation *type and entity coordinates*, or by count delta, instead of COM identity.
   - The removed-check at ~l.1537 compares total relation counts, but the dimension itself adds a relation, so it gives a false warning.
   - An anchor point that is already Fixed is refused. It should apply the dimension without adding a temporary relation.
2. **#14 undo inside a sketch:** `_sketch_db_mode` (AddToDB=True) bypasses the undo stack, so undo after `draw_line` does nothing.
   - Option A: document that undo can't remove draw_* geometry and add a `delete_sketch_segment` tool.
   - Option B: don't use AddToDB for single entities. This needs Zach's call, because AddToDB is what fixed #1.
   - Recommendation: A.
3. **#10 `force_all`:** `sw_file.py:~708` raises `TypeError: 'bool' object is not callable`, because the late-binding property and method are confused. `ok` stays true. Route the member through `flag_methods`, or call it correctly.

## Next steps
1. Brief a Sonnet implementer for bugs 1 and 3, plus option A of bug 2 if Zach agrees.
2. Have a different agent verify offline.
3. Re-run the three live scripts serially.
4. 🧑 Ask Zach to commit batch 2.
5. Remaining work:
   - #16 loft: a live investigation of start points/twist. Repro: 240×70 R16 → 234.4×70 R16.
   - The `whats_wrong` exception swallowing.
   - Triage what's left into PLAN Phase 7.
6. Remind Zach to restart the MCP server in his clients to pick up the new code. Check whether `SW_MCP_OUTPUT_ROOT` is set in the client configs.

## Gotchas
- The MCP server in a session runs the code from its start time. Live scripts must call `server.call_tool` directly, with `SW_MCP_OUTPUT_ROOT` set for the run.
- COM `==` works for CDispatch in some cases (sketch identity), but not for fresh relation wrappers.
- The full live batch took about 100 minutes in one agent. Next time, split it into one agent per script.
