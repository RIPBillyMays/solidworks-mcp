# Phase 5 fixes: live verification (SOLIDWORKS 2017 SP05)

Scripts (via `server.call_tool`, `SW_MCP_OUTPUT_ROOT=sandbox\fixes_probes`, scratch parts only, all closed, nothing saved except screenshots):
`tests/live_p5_fixes_feature.py`, `tests/live_p5_fixes_sketch.py`, `tests/live_p5_fixes_file_inspect.py`. Logs: `sandbox/fixes_probes/*.log`.
Start state: 0 documents open. End state: 0 documents open. No modal dialog hung.

Result: 52 of 61 checks PASS, 8 FAIL (3 real code bugs, 1 limitation, 4 sub-checks of those), 1 SKIP.

## Results

| Finding | Check | Result | Evidence |
|---|---|---|---|
| #5 | Front boss +normal d10, first boss | PASS | bbox Z 0..10, vec [0,0,1], volume_delta 4000 == volume |
| #5 | Front cut +normal d3 (full profile) | PASS | bbox Z 3..10, delta -1200, reversed_automatically false |
| #5 | Default cut (no direction) auto-reverses | PASS | reversed_automatically true, bbox Z 5..10, delta -800 |
| #5 | Boss -normal / cut -normal | PASS | boss Z -10..0 vec [0,0,-1]; cut d3 gives Z -10..-3, delta -1200 |
| #5 | Explicit +normal cut with no material there | PASS | ok:false, not retried, volume unchanged 2800 |
| #5 | Mid-plane body: cut +normal / -normal d5 | PASS | Z -5..0 and Z 0..5, delta -2000 each; boss reports `symmetric` |
| #5 | Top plane +/-normal, Right plane +/-normal | PASS | Top vec [0,±1,0], Y 0..10 / -10..0; Right vec [±1,0,0], X 0..10 / -10..0 |
| #5 | direction + reverse(false) rejected | PASS | ok:false, nothing built (volume 0); reverse alone still works (Z -10..0) |
| #8 | Stale select on "Keep", delete_feature(Target) | PASS | only Target gone, Keep stays, count 20->19 |
| #8 | Loose name 'keep'; unknown name | PASS | 'keep' deletes Keep; NoSuchFeature refused |
| #8 | Dependent delete | PASS | deleting BaseBoss reports FilletChild under also_deleted, volume 0 |
| #9 | Suppress child twice | PASS | second call already:true, ok:true; state True, volume 4500->4000 |
| #9 | Suppress parent | PASS | side_effects = ChildSketch, ChildBoss; states verified with IsSuppressed2; volume 0 |
| #9 | Suppress an already-suppressed parent | PASS | already:true |
| #9 | Unsuppress parent | PASS | Parent False, child stays True (SOLIDWORKS does not cascade unsuppress). The first script run expected children restored; that was a wrong expectation and was corrected |
| #9 | Unsuppress child sketch and boss | PASS | volume back to 4500 |
| #17 | Variable fillet on 3-edge chain | PASS | ok:false with clear message; volume unchanged; vertex_radii also refused |
| #17 | Constant fillet propagate=false, one edge of tangent chain | PASS (recorded) | NOT propagated: removed 23.04 mm3 vs single-edge expectation 21.46 (full chain ~58); faces 7->8 (+1 cylinder); options=2 |
| #17 | Variable fillet 1->3, single edge, propagate=false | PASS | built, removed 28.0 mm3 (estimate ~23) |
| #7 | edit_sketch A1/A2/A1/A3 then list_sketch_segments, close_sketch | PASS | all name the right sketch. Identity path alone (hint cleared) also returns the right name every time |
| #11 | Rect 40x20, fillet corners (40,20),(0,0) R3 | PASS | 2 arcs R3 at (3,3),(37,17); 4->6 segments; extrusion volume 3980.686 == hand calc |
| #11 | Repeat on filleted corner; corner with no endpoint | PASS | both ok:false, count stays 6 |
| #12 | construct_original | PASS | 4 sources construction, 4 offset lines (24 mm) not; construction_flagged 4 |
| #13 | anchor=start geometry | PASS | start stays (0,0), end moves to (47.43,15.81), length 50 |
| #13 | anchor=start: no temp Fixed left | PASS | Fixed count 0->0 (the dimension itself adds one type-1 relation, so the total goes 0->1) |
| #13 | anchor=start: result reports `anchor_relation_removed:true` | FAIL | returns false plus a false "could not be removed" warning. BUG 1 |
| #13 | anchor=end geometry | PASS | end stays (30,60), start moves, length 50 |
| #13 | anchor=end: no temp Fixed left | FAIL | Fixed relation leaked (Fixed count 0->1, ambiguous:true). BUG 1 |
| #13 | User Fixed on the anchor point survives, relation count unchanged | PASS | 4->4 relations, Fixed 2->2 (baseline already held the leak above) |
| #13 | anchor=start on an already-Fixed point applies the dimension | FAIL | ok:false "did not add the temporary Fixed relation". No damage, but the dimension is not applied. BUG 1b |
| #14 | undo after draw_line inside a sketch | FAIL | ok:false, segments 2->2, line not removed. BUG 2 |
| #14 | redo in sketch | FAIL | ok:false, "not supported on 2017" (known limitation, expected) |
| #14 | Deep undo reporting | PASS (recorded) | ok:false, sketch_open true |
| #15 | Front / Top / Right axes | PASS | Front x[1,0,0] y[0,1,0]; Top y[0,0,-1] n[0,1,0]; Right x[0,0,-1] n[1,0,0]. Rect (10,0)..(12,2) measured by bbox lands at the expected model coords on all three planes |
| #15 | Sketch on -Z-facing face | PASS | normal [0,0,-1], x=[-1,0,0], y=[0,1,0], x cross y == normal |
| #10 | rebuild_document on a clean part, repeated, and force_all | PASS | ok:true, problems [], warnings [], rebuild_returned true. ForceRebuild3 fallback not needed (second rebuild still returns true) |
| #10 | `force_all=true` raw call | FAIL (minor) | ok stays true, but `rebuild_error` = "ForceRebuildAll failed: TypeError: 'bool' object is not callable". BUG 3 |
| #10 | Part with a real error or warning: errors/warnings split | SKIP | Could not provoke one. 2017 rebuilt a fillet of R40 on a 10 mm box, a disjoint merged boss, an underdefined sketch; edit_feature rolls back chamfer and shell edits. Split still needs a real error case |
| #18 | list_faces on 231-face part (15x15 holes) | PASS | default: 200 returned, truncated true, total 231, offset 0; paging by offset gives indices 0..230 exactly once, last page truncated false |
| #18 | limit=5 offset=3; offset near the end | PASS | 5 returned, truncated true, first index 3; 3 returned, truncated false |
| #18 | feature= filter (COM equality) | PASS | HolesPat 224 + Hole0 1 == the 225 cylinder faces; Plate gives 6 planes only; unknown feature refused |
| #18 | within_box on faces | PASS | [229] equals an independent filter; swapped corners give the same |
| #18 | list_edges paging, feature=, within_box | PASS | 462 edges: default 200, truncated, total 462; HolesPat gives 448 circles; within_box [446,458,459] equals the independent filter (circles are matched by their `point_mm`) |
| #19 | capture_screenshot save_as | PASS | `sandbox/fixes_probes/screenshots/probe19.png`, 779090 bytes, valid PNG signature, saved_path matches; no save_as leaves no file; extension appended |
| #19 | Bad names `../x`, `a/b.png`, `..\x.png`, `C:x.png`, `CON`, `NUL.png` | PASS | all ok:false, nothing written |

## Bugs (not fixed, per instructions)

1. **#13 anchor relation cleanup** (`solidworks_mcp/sw_sketch.py` `_temporary_fixed`).
   - Cause A, line 1519: `same_com_object` (`==` on wrappers) returns False for the same ISketchRelation fetched by two `GetRelations` calls. Once the sketch already holds any relation, the whole list looks new, `len(added) != 1`, nothing is deleted and the temporary Fixed stays. The verifier flagged this risk. It is real.
   - Cause B, line 1537: `removed` compares the relation count with the pre-add count, but the dimension adds its own relation (GetRelationType 1). The Fixed is deleted correctly, yet the tool reports `removed:false` plus a false warning.
   - Fix: identify the new relation without COM identity. Take type-17 relations after minus before (compare by `GetRelationType==17` and the entity coordinates of the anchor point, or by count of type-17), delete that one, and verify success by the type-17 count returning to its baseline, not the total.
   - 1b: if the anchor point already has a Fixed relation, skip the temporary relation instead of failing (the AddRelation duplicate is not added, line 1517).
2. **#14 undo/redo in a sketch.** Lines made by `draw_line` use `_sketch_db_mode` (`sw_sketch.py:147`, used at 626, 682, 750 and others), which sets `AddToDB=True`. In SOLIDWORKS 2017 that bypasses the undo stack. Raw probe: a line created with `AddToDB=False` is removed by `EditUndo2(1)` (segments 2->1), while the same call after `draw_line` is a no-op. `sw_select._step_in_sketch` itself is correct. Options: document that undo does not work on API-drawn geometry, or add a `delete_sketch_segment` tool.
3. **#10 force_all.** `solidworks_mcp/sw_file.py:708`, `extension(doc).ForceRebuildAll()`: it is a property in the late binding, so the call raises the TypeError. Fix: `value(extension(doc), "ForceRebuildAll")`, which tolerates both.

Test notes: `server.log` rotation raises PermissionError (the live MCP server holds the file). It is harmless noise on stderr. `list_edges` on 462 edges takes about 165 s (per-edge COM reads), and drawing circles one by one is O(n^2), so the 225 holes are built with a linear pattern.
