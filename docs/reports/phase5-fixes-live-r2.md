# Phase 5 fixes: Revision 2 verification (offline review + live, SOLIDWORKS 2017 SP05)

Scripts: `tests/live_p5_fixes_sketch.py` (30 PASS + 2 FAIL), `tests/live_p5_fixes_file_inspect.py` (run in full: 27 PASS; the 2 FAILs in that run were caused by me closing a doc mid-test, see the note; f10 re-run alone: clean, 1 SKIP as before).
Via `server.call_tool`, `SW_MCP_OUTPUT_ROOT=sandbox\fixes_probes`, scratch parts only, nothing saved. Start: 0 docs. End: 0 docs. Logs: `sandbox/fixes_probes/r2_*.log`.
Offline: 636 unit tests OK; MCP smoke handshake OK (171 tools).

## Offline review

| Check | PASS/FAIL | Evidence |
|---|---|---|
| Anchor matching: can a user Fixed be deleted? | PASS | `_temporary_fixed` (sw_sketch.py:1643-1690) deletes only when Fixed count rose by exactly 1 AND (no prior Fixed, or exactly one Fixed references the anchor X/Y). Zero or several matches means nothing is deleted. Count unchanged with prior Fixed means "already fixed": nothing added, nothing deleted. |
| Anchor matching: mis-identification residual risk | NOTE | If the user already holds a Fixed on another entity at the same coordinates as the anchor (e.g. another line's coincident-but-unrelated endpoint), `_references_point` could match two, so it refuses to delete (safe, only warns). |
| Anchor already-Fixed detection | NOTE | "Count unchanged and fixed_before>0" assumes the anchor itself is the Fixed one. If the anchor is NOT fixed but AddRelation silently failed while some other Fixed exists, the dimension is applied unanchored, reported `anchor_already_fixed:true`. Low likelihood, not observed. |
| delete_sketch_segment arc direction | **FAIL (bug)** | sw_sketch.py:628-630 computes `span` and `offset` assuming CCW from start to end. A clockwise arc (GetRotationDir -1, start/end kept in request order) gets span = 2*pi - real sweep: its real span is rejected (offset > span means distance to nearer end only) and the opposite arc of the circle is accepted. Confirmed live (below). |
| Suite | PASS | `unittest discover`: 636 OK. `mcp_smoke_client.py`: ok, 171 tools incl. delete_sketch_segment. |
| sw_file.py force_all | PASS | sw_file.py:708-713 reads `value(extension(doc), "ForceRebuildAll")`; exception path gives ok:false with rebuild_error. |
| sw_select.py undo hint | PASS | sw_select.py:63 (description), 95 (`_SKETCH_UNDO_HINT`). |

Suggested fix for the arc bug (sw_sketch.py ~626): read `rot = int(value(segment, "GetRotationDir"))` (try/except default 1); if `rot == -1`, swap the two angles when computing span/offset (measure from end to start CCW, i.e. `a0 = atan2(ey-cy, ex-cx)`, `span = (atan2(sy-cy, sx-cx) - a0) % 2pi`, `offset = (atan2(y-cy, x-cx) - a0) % 2pi`). Add a unit test with a CW arc fake.

## Live

| Check | PASS/FAIL | Evidence |
|---|---|---|
| #13 setup: sketch already has relations | PASS | total relations 1 (horizontal on seg 3) before first anchored dimension |
| #13 anchor=start geometry | PASS | start (0,0) unchanged, end (30,10) -> (47.43,15.81), length 50 |
| #13 anchor=start: no leftover Fixed | PASS | Fixed count 0 -> 0 (total 1 -> 2: the dimension's own type-1 relation) |
| #13 anchor=start: no false warning | PASS | `anchor_relation_removed:true`, message "Added a dimension.", no Warning |
| #13 anchor=end geometry (2nd call, relations exist) | PASS | end (30,60) unchanged, start moved to (-17.43,44.19), length 50 |
| #13 anchor=end: no leftover Fixed | PASS | Fixed 0 -> 0, removed true, ambiguous None (previous run leaked here) |
| #13 user Fixed survives | PASS | Fixed 1 -> 1, total 4 -> 5 (+1 = dimension's own relation) |
| #13 already-Fixed anchor | PASS | ok, start kept (0,100), length 40, `anchor_already_fixed:true`, `anchor_relation_removed:true`, no Warning |
| #10 force_all | PASS | ok:true, `rebuild_error` null, no "TypeError" in result, `rebuild_returned` true |
| #14 undo in sketch hint | PASS | result message ends "...created outside the undo stack ... use delete_sketch_segment instead."; segments 2 -> 2 (ok:false is expected) |
| delete by index | PASS | index 1: ok, 2 -> 1; deleted record returned |
| delete: out-of-range / neither / both | PASS | all ok:false, count unchanged |
| delete by point on a line | PASS | point 0.1 mm off line mid: that line gone, 2 -> 1 |
| delete by point far away | PASS | ok:false "No line or arc passes within 0.5 mm" |
| delete by point on CCW arc (45 deg midpoint) | PASS | ok, 2 -> 1, deleted type arc |
| delete CW arc: point on circle but NOT on arc (135 deg) must be refused | **FAIL** | ok:true, the CW arc was deleted (count 2 -> 1). Bug at sw_sketch.py:628-630 |
| delete by point on the CW arc midpoint (-45 deg) | **FAIL** | "No line or arc passes within 0.5 mm of that point", count unchanged. Same bug. (This check ran after the arc had already been deleted by the previous wrongly-accepted call, but it is a bug on its own: the same code rejects the real midpoint, shown by the 135 deg acceptance.) Re-run after the fix with a fresh arc each. |
| ambiguous point refused | PASS | shared corner of two lines: ok:false, candidates [1,2], count unchanged |
| delete with no sketch open | PASS | ok:false "No sketch is open" |
| Previous checks (#7, #11, #12, #15, #18, #19, #10 clean) | PASS | all still pass; #10 error/warning split still SKIP (no error could be provoked) |

Note: during the full file_inspect run, my own rerun attempt closed its in-progress scratch part ("Part128"), which made 2 f10 sub-checks (deliberate-error and restore) fail in that log. Re-running `f10 f10_warning` alone on a clean state gave 6 PASS + 1 SKIP, as before. Nothing else was touched; all docs were mine.

## Revision 3 live

Live on SW 2017, new part on Front Plane, via `server.call_tool` (new section `f16` in `tests/live_p5_fixes_sketch.py`, SW_MCP_OUTPUT_ROOT=sandbox\fixes_probes). No documents were open at start; everything created was closed.

| Check | Result |
|---|---|
| CW arc (direction -1): point on circle but off the arc refused, count unchanged | PASS |
| CW arc: true midpoint deletes it, count -1 (also on a second CW arc) | PASS |
| CCW arc: off-arc point refused, count unchanged | PASS |
| CCW arc: midpoint deletes it, count -1 (also on a second CCW arc) | PASS |
| Full `live_p5_fixes_sketch.py` | 38 PASS, 0 FAIL, exit 0, no regressions |

The clockwise-arc bug is fixed.
