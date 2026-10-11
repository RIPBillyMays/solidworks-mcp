# Phase 5 batch A: feature tools (offline)

Status: implemented and unit tested offline (183 tests pass, smoke client lists undo, redo, select_entity, clear_selection). Nothing run against live SOLIDWORKS. Not committed.

## What changed
- `sw_core.py` (additive): `FEATURE_DIALOG_TOGGLES = (10, 77)` and `dialogs_suppressed(app=None, toggles=...)`, a context manager that turns each toggle off independently and restores it in `finally`. The legacy `dimension_dialog_suppressed` is untouched.
- `sw_feature.py`: `boss_extrude`, `cut_extrude`, `revolve` rewritten around a shared `_ExtrudePlan`. Defaults reproduce the previous argument lists exactly (tested). All three run inside `dialogs_suppressed()`.
  - End conditions: blind, through_all, through_all_both (still mapped to two through-all), through_next, up_to_vertex, up_to_surface, offset_from_surface (depth_mm is the offset; `offset_reverse` flips), up_to_body, mid_plane.
  - `target`: `face` | `vertex` | `body` | `body_name` | `feature`+`face_index` | `point{x_mm,y_mm,z_mm,type}`. Selected after the profile sketch with mark 1; `target2` uses mark 2. Reselected on the cut retry.
  - Second direction: `end_condition2`, `depth2_mm`, `draft2_deg`, `draft2_outward`, `target2`, `offset2_reverse`.
  - Draft in/out: `draft_outward` on both boss and cut.
  - `thin` {thickness_mm, type one_direction|mid_plane|two_directions, thickness2_mm, reverse, cap_ends, cap_thickness_mm} via `FeatureExtrusionThin2` / `FeatureCutThin2`.
  - Cut `flip_side`, boss `merge`.
  - Revolve: `angle2_deg` (two directions), `mid_plane`, `thin` (via FeatureRevolve2 ThinType 0/1/2/3).
- New `sw_select.py` (imported in `server.py`): `undo`, `redo` (EditUndo2/EditRedo2, report feature counts before and after), `select_entity` (name+type via SelectByID2, point via SelectByID2, or ray via SelectByRay), `clear_selection`.
- Verified signatures against the installed 2017 typelib (FeatureExtrusion3 23 args, ExtrusionThin2 30, Cut4 27, CutThin2 29, Revolve2 20).

## FORK_CHANGES lines
- `solidworks_mcp/sw_core.py`: added `FEATURE_DIALOG_TOGGLES` and `dialogs_suppressed()` (generic multi-toggle dialog guard; `dimension_dialog_suppressed` unchanged).
- `solidworks_mcp/sw_feature.py`: `boss_extrude`/`cut_extrude`/`revolve` extended: all end conditions with `target` selection, second direction, draft in/out, thin features (FeatureExtrusionThin2/FeatureCutThin2), revolve two-direction/thin; feature creation wrapped in `dialogs_suppressed()`.
- `solidworks_mcp/sw_select.py` (new): `undo`, `redo`, `select_entity`, `clear_selection` tools; registered with one import line in `solidworks_mcp/server.py`.
- `tests/test_sw2017_batchA_feature.py` (new): offline tests.

## Live verification checklist (serial, Zach's SW, sandbox/ only)
1. Regression: `boss_extrude` blind 10 mm, `cut_extrude` through_all, `revolve` 360 give the same volume as before.
2. Up to surface: box, sketch on a plane offset from it, `up_to_surface` with `target.face`; check bounding box meets the face.
3. Up to vertex and up to body (second body); check extent.
4. Offset from surface: depth 2 mm with and without `offset_reverse`; check both stop 2 mm short or past.
5. Confirm MARK for direction 2 end-condition entity (assumed 2): `end_condition2=up_to_surface` with `target2`. If it fails, try mark 32 in `_mark_end_dir2`.
6. Target by `body_name`, by `feature`+`face_index`, by `point` coordinates.
7. Second direction blind (depth 10 + depth2 5): total length 15; with `draft2_deg`.
8. Draft in vs out: volume smaller vs larger than the undrafted prism.
9. Thin: one_direction, two_directions (volume vs formula), mid_plane (assumed Thk1 = Thk2 = t/2: verify wall is centred and total is t), cap_ends.
10. Thin cut and cut `flip_side`.
11. Revolve: `angle2_deg`, `mid_plane` (verify it is symmetric), thin (ThinType enum, esp. mid_plane = 2 and `reverse` = 1).
12. Dialog guard: with "Show errors every rebuild" ON, make a feature that errors; the call returns, and the toggle is back ON afterwards. Same for dimension input.
13. `undo` after a boss: feature count drops by one and volume restored; `redo` reverses it. Check how many steps one feature takes.
14. `select_entity` by name (e.g. `Front Plane`, type PLANE), by point on a face, by ray at a face; `clear_selection` empties it (selected_count 0).

## Risks and open questions
- Selection mark for second-direction entity (2) and thin mid_plane representation are from memory of the API, not from the typelib; checklist items 5 and 9.
- Type strings accepted by `select_entity` are SelectByID2 names (FACE, EDGE, VERTEX, PLANE, AXIS, SKETCH, BODYFEATURE, SOLIDBODY, COMPONENT, ...); only FACE/EDGE/VERTEX/SOLIDBODY/SURFBODY work with ray.
- `tests/test_sw2017_enums.py` flags uppercase module-level numeric constants, so the marks are lowercase `_mark_end_dir1/2` rather than adding NOT_ENUM entries.
