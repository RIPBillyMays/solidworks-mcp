# Phase 5 fix 1 verification (offline)

Tests: 495 OK (unittest discover). Smoke client: 169 tools, draw_polyline listed.

| # | Criterion | Result |
|---|-----------|--------|
| 1 | AddToDB/DisplayWhenAdded set + restored in finally, all 8 tools | PASS (`_sketch_db_mode`, sw_sketch.py:142-168; all 8 tools use it) |
| 2 | Read-back verification, mm units, ok:false | PASS with risk (below) |
| 3 | draw_polyline validation, closed, shared vertices | PASS (validation before COM, 572-590; closing pair appended; vertices are the identical float tuples) |
| 4 | API members / late binding | PASS. All members in sw2017_api_members.txt. AddToDB/DisplayWhenAdded are zero-arg properties; plain setattr on `doc.SketchManager` is valid under dynamic dispatch (PROPPUT); read via `safe`/`value` copes with property or method. Create* go through flagged `sketch_manager(doc)`. |
| 5 | Apache note + FORK_CHANGES | PASS (sw_sketch.py:15; FORK_CHANGES.md:63) |
| 6 | Tests/smoke | PASS |
| 7 | Auto-relation / merge risk | Code does NOTHING about it |

## Findings
- Rectangle verification uses the bounding box of all endpoints (order independent) - correct. Polygon dedupes corners, checks centroid, circumradius (circumscribed uses r/cos(pi/n), consistent with tool text) and side count - correct and order independent.
- RISK (sw_sketch.py:299-307, 268-308): `draw_arc` with `direction=-1`. SOLIDWORKS stores sketch arcs counter-clockwise, so Get Start/EndPoint2 likely return the requested end/start swapped: a false `ok:false`. The 3-point arc accepts a swap; draw_arc does not. Also arc sweep side (which of two arcs between the same endpoints) is never verified. Suggest accepting the swapped ends when direction=-1 and checking the sweep, e.g. via a mid-point or angle.
- Unverified: whether `segment.ConstructionGeometry = True` is permitted while AddToDB is on (draw_line:545, polyline:605).
- Items 4/7 cannot be proven offline (no coincident/merge code exists; tests use a fake manager).

## Risk 7: no coincident relations or merged endpoints
Nothing adds relations. Consecutive lines are exact to 1 um, but they may be separate sketch points with no relations.

## Live probe checklist
1. Read AddToDB and DisplayWhenAdded before and after one call; confirm they are restored, and also after a forced failure.
2. Crowded sketch plus the 10-point star at 0.6 mm steps: coordinates exact (the original repro).
3. draw_polyline closed square/star: `GetSketchSegments` count, and the relation count per vertex (coincident present?). If absent, compare `ISketchPoint` identity for adjacent endpoints.
4. get_sketch_status (no "open contour"/gap), then boss_extrude the closed polyline: volume > 0 and the expected value.
5. Same for 4 draw_line calls forming a rectangle, plus an arc-and-line mixed profile.
6. Rectangle and polygon: relations created (rectangle normally gets H/V and coincident), verify:true, correct results.
7. draw_arc direction=1 and -1 with a quarter arc: no false failure, correct sweep.
8. construction=true with AddToDB on: the segment is construction.
9. Sketch still editable afterwards: add_dimension / add_relation on the new geometry, rebuild, no error.
10. If the merge fails: add a post-step that adds coincident relations between consecutive endpoints (or turn AddToDB off for polyline and rely on the verifier).
