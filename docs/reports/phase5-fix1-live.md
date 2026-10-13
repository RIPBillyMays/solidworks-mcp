# Phase 5 fix 1: live test (SOLIDWORKS 2017, 2026-10-12)

Script: `tests/live_p5_fix1_sketch.py` (calls handlers directly, new code). Startup guard: no documents were open. Every scratch part was force-closed; none were left open. Nothing was saved. Raw results: `sandbox/fix1_probes/results.json`.

| Check | Result | Evidence |
|---|---|---|
| 1a AddToDB / DisplayWhenAdded restored after draws | PASS | Before (False, True). After draw_line, draw_circle, draw_rectangle, draw_polyline: (False, True) each time. |
| 1b restored after failing draws | PASS | Zero-length line reached COM and returned ok:false "did not create a line"; state (False, True). Zero-radius circle returned without raising; state (False, True). No Create* exception could be forced, so the raise path rests on the offline test. |
| 2 crowded sketch (star + staircase + 0.4 mm near-line) | PASS | 18 lines in one sketch on Right Plane, all ok:true and verified:true. Worst endpoint error 4.8e-07 mm, read back independently via list_sketch_segments. The original 1c shifts (up to about 1.2 mm) are gone. |
| 3 arc centre 0.5 mm from existing arc centre | PASS | Requested centre (0.5,0) R5; actual (0.5,0) R5.0; both calls ok:true. The original repro 1d snapped to (0,0) R5.5. |
| 4 closed 10-point star polyline then boss_extrude 5 mm | PASS | ok:true, verified:true, 10 segments, worst error 4.8e-07 mm. get_sketch_status reads "under_defined", not open or gapped. Extrude ok. Volume 587.7853 mm3 vs shoelace area x 5 = 587.7853. So AddToDB segments form a valid closed profile. |
| 5 four draw_line calls forming a 20x10 rectangle, extrude 5 | PASS | All four ok:true. get_sketch_status "under_defined". Volume 1000.0000 vs expected 1000. |
| 6 draw_arc direction 1 and -1 | PASS | dir=1: ok, start (10,0) end (0,10), GetRotationDir=1, sweep 90 deg, mid 45 deg. dir=-1: ok, start (50,0) end (40,-10), GetRotationDir=-1, sweep 90 deg clockwise, mid -45 deg. Finding: 2017 does NOT swap start/end for a clockwise request. It keeps the request order and reports GetRotationDir=-1. This is the opposite of the assumption in Revision 1, but the verifier accepts both orders, so there is no false failure. |
| 7 draw_polyline construction=true | PASS | ok:true, 3 segments, all 3 report construction:true (ConstructionGeometry is accepted while AddToDB is on). |
| 8 add_dimension on a polyline segment | PASS | add_dimension ok, applied:true. Segment 0 length went from 20.0 to 25.0 mm (requested 25). |
| 9 rectangle / polygon / centerline / circle | FAIL (polygon only) | draw_rectangle, draw_centerline and draw_circle: ok:true, verified:true. draw_polygon: ok:false, "created a polygon but not where requested (centre; ... sides: requested 6, actual 7)". The polygon geometry itself is correct; the verifier is wrong (see bug). |

## Code bug (not fixed, per instructions)
`solidworks_mcp/sw_sketch.py:844` (via `_flat_segments`, 363-371) and `_verify_polygon` (406-457). `CreatePolygon` on 2017 returns 7 segments for a hexagon: the 6 edges plus a construction circle (listed as an "arc" with centre and radius 10). The verifier counts the circle as a side (sides: 7) and reads its odd "corner" into the centroid (actual centre (61.18, 0.36) vs requested (60,0)). Every draw_polygon call fails verification with false ok:false.
Suggested fix: in `_verify_polygon` (or before it) keep only line segments, for example `GetType == 0`, and compare `sides` to that count.

## Related observation (pre-existing, not caused by fix 1)
The `inscribed` argument has no effect on 2017. `CreatePolygon(..., Inscribed=True/False)`, with AddToDB on or off, always places a corner at the given point (corner at (10,0), circumradius 10). So `inscribed=false` (point at an edge midpoint, per the tool text) is wrong, and `_verify_polygon` would report a circumradius mismatch (requested r/cos(pi/n)) even after the construction-circle fix. Suggest either dropping the flag from the tool text or computing the corner point from the midpoint before calling CreatePolygon when `inscribed=false`.
