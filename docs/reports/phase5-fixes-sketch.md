# Phase 5 sketch fixes: findings #7, #11 to #15

## Design
- **#7 open-sketch label.** `sw_core.open_sketch_name(doc)` compares `ActiveSketch` with every sketch feature's `GetSpecificFeature2` (`same_com_object`, which uses `==`; win32com `CDispatch.__eq__` compares interface pointers; `_oleobj_` is deliberately not referenced because the compat scanner flags it). Fallbacks: the name recorded by the last `create_sketch`/`edit_sketch` (`set_open_sketch_hint`), then the newest sketch. Used by `enumerate_sketch_segments` (so `list_sketch_segments`), `create_sketch`, `close_sketch`. `close_sketch` clears the hint.
- **#11 `sketch_fillet(corners=[{x, y}])`**, mm, `tolerance_mm` default 0.01. Per corner: re-read segments; reject if an arc's tangent intersection (centre + (chord mid - centre) * r^2 / d^2) lies at the corner (already filleted); require exactly two line/arc segments with an endpoint there; select them with `select_object`; `SketchFillet2`; success = segment count +1. Stops at the first failure and reports the corners already done. Returns `filleted_corners_mm` and the updated `segments`. Index mode (`selection`) unchanged; `radius_mm` is now the only required arg; both modes together are rejected.
- **#12 `sketch_offset(construct_original)`.** Needs `sketch_segments` in the selection. Source set = selected segments plus (when `chain`) everything connected end to end. Flags `ConstructionGeometry=True` on the pre-held segment objects after a successful offset; returns `construction_flagged`.
- **#13 `add_dimension(anchor)`.** The first selected segment must be a line (`sketch_segments`). Its start/end `ISketchPoint` gets a Fixed relation via `ISketchRelationManager.AddRelation` (code 17, same path as `add_relation`), the old body runs (`_add_dimension`), then `ISketchRelationManager.DeleteRelation` removes it in a `finally`. The new relation is found by diffing `GetRelations(0)` before and after, so a user's own Fixed relation is never deleted. Removal is verified by relation count; `anchor_relation_removed` is returned, and a warning is appended to the message if it failed. No fallback was needed: all members are in the 2017 list.
- **#14 undo/redo in a sketch.** When `ActiveSketch` is set, `_step_in_sketch` compares (segment count, point count) before and after. Reports `segments_*`, `points_*`, `in_sketch`, `sketch_changed`. If the step closed the sketch, ok with `sketch_open:false`. Outside a sketch the feature-list logic is untouched.
- **#15 axes.** `_sketch_axes` inverts `ISketch.ModelToSketchTransform` and reads `ArrayData` with the repo's verified layout (element (row, col) at 3*col+row; translation at 9..11): `sketch_x_axis`, `sketch_y_axis`, `normal` are the columns, `origin` is the translation in mm. Added to `create_sketch` and `edit_sketch` results; omitted (never an error) if the transform is unreadable.

## Files changed
- `solidworks_mcp/sw_sketch.py`
- `solidworks_mcp/sw_select.py`
- `solidworks_mcp/sw_core.py` (additive: `set_open_sketch_hint`, `same_com_object`, `open_sketch_name`; one edit in `enumerate_sketch_segments`)
- `tests/test_sw2017_sketch_edit_fixes.py` (41 tests)
- this report

New SW members used (all in `sw2017_api_members.txt`): `ISketchRelationManager.GetRelations/DeleteRelation`, `ISketchRelation.GetRelationType`, `IMathTransform.Inverse/ArrayData`, `ISketch.ModelToSketchTransform`, `ISketch.GetSketchPoints2`, `IModelDoc2.EditUndo2/EditRedo2` (existing).

## Results
Full suite: 609 tests OK. `mcp_smoke_client`: 170 tools.

## Proposed FORK_CHANGES text
> **Sketch editing fixes (Phase 5 field findings #7, #11-#15)**: `sw_core.py` adds `open_sketch_name` (COM-identity match of the open ISketch to its feature, with hint and newest-sketch fallbacks) and uses it in `enumerate_sketch_segments`. `sw_sketch.py`: `create_sketch`/`edit_sketch` report `sketch_x_axis`, `sketch_y_axis`, `normal`, `origin`; `close_sketch` names the right sketch; `sketch_fillet` accepts `corners` (resolved by endpoint match, one at a time, rejects already-filleted corners); `sketch_offset` gains `construct_original`; `add_dimension` gains `anchor` (temporary Fixed relation, removed afterwards). `sw_select.py`: `undo`/`redo` judge success by sketch segment and point counts while a sketch is open.

## Live-probe checklist
1. Open Sketch1..3, `edit_sketch` Sketch1, then `list_sketch_segments`, `close_sketch`: names are Sketch1 (identity matching via `==` on late-bound wrappers is unverified live).
2. `create_sketch` on Front, Top, Right: axes match Front x->X y->Y; Top y->-Z; Right x->-Z y->Y. Confirm the `ArrayData` column convention (if reversed, x/y would come back transposed on Top/Right) and that `origin` is in the right units/frame.
3. Filleting the 4 corners of a rectangle by `corners`; repeating a corner is rejected; a radius too large reports "did not fillet". Check `GetCenterPoint2`/`GetStartPoint2` work on arcs after a fillet (needed by the already-filleted check).
4. `sketch_offset construct_original` on a closed chain: sources become construction, the offset geometry does not. Confirm `ConstructionGeometry` set on a pre-offset wrapper still works after the offset.
5. `add_dimension anchor=start/end` on a free line: the other end moves; afterwards the relation count is back to its start and `anchor_relation_removed` is true. Check `ISketchRelationManager.GetRelations(0)` filter value, that `AddRelation` accepts a single `ISketchPoint` array, and that `GetRelationType` returns 17.
6. Draw a line, `undo` while the sketch is open: ok with segments n -> n-1. Also `undo` after the last segment (does it close the sketch?).


## Revision 2 (live bugs 1 and 2)

**#13 anchor (`_temporary_fixed`).** COM identity is no longer used. The Fixed-type (17) relation count is taken before `AddRelation` and after. Count +1 with no prior Fixed: that one is ours. Count +1 with prior Fixed relations: ours is the single Fixed relation whose `GetEntities` has an entity at the anchor's X/Y (1e-9 m); zero or several matches mean warn and delete nothing. Count unchanged with prior Fixed present means the point was already Fixed: skip the temporary relation, apply the dimension, report `anchor_already_fixed:true` and `anchor_relation_removed:true`. Count unchanged with none prior still refuses. Removal is verified as "Fixed count back to the starting value", so the dimension's own type-1 relation no longer causes a false warning. The delete still has to follow the dimension (the point must be held during it). Tests use fakes that return fresh, never-equal wrappers on each fetch, plus a dimension that appends a type-1 relation; the old identity-patch test was replaced by an ambiguous-match test.

**#14 undo option A.** New tool `delete_sketch_segment` (index or `point{x_mm,y_mm}` + `tolerance_mm`, default 0.5): requires an open sketch, ClearSelection2, select without append, `Extension.DeleteSelection2(0)`, verifies count fell by exactly 1, returns `deleted` (type, endpoints), `segments`. An ambiguous point (two segments in tolerance, e.g. a shared corner) is refused with `candidates`. Point matching covers lines and arcs only (arcs assumed CCW start to end); use index for splines and ellipses. `undo` description and its unchanged-in-sketch result now say draw_* geometry sits outside the undo stack and point to this tool.

### FORK_CHANGES text (for merge)
- `solidworks_mcp/sw_sketch.py`: `_temporary_fixed` identifies the temporary Fixed relation by type and anchor coordinates and verifies removal by Fixed-type count (live 2017: `==` on relation wrappers is always False); skips an already-Fixed anchor. New tool `delete_sketch_segment` (170 -> 171 tools).
- `solidworks_mcp/sw_select.py`: `undo` description and unchanged-in-sketch message explain draw_* geometry is outside the undo stack and point to `delete_sketch_segment`.
- `solidworks_mcp/sw_file.py`: `rebuild_document(force_all)` reads `ForceRebuildAll` via `value()` (a property on 2017, so calling it raised TypeError).
