# Phase 5 fix 1: exact sketch placement and verification

## Design
- `_sketch_db_mode(doc)` (sw_sketch.py): sets `SketchManager.AddToDB=True`, `DisplayWhenAdded=False`; previous values restored in `finally` (also when Create* raises); then `GraphicsRedraw2` (swallowed if declined). No user preferences touched.
- Used by draw_line, draw_centerline, draw_circle, draw_rectangle, draw_arc, draw_3point_arc, draw_polygon, draw_polyline. Other tools (ellipse, slot, spline, point) unchanged (out of the requested list).
- Verification (tolerance 1e-6 m): line endpoints via ISketchLine.GetStartPoint2/GetEndPoint2; circle/arc via ISketchArc.GetCenterPoint2/GetRadius/GetStartPoint2/GetEndPoint2 (arc end compared after projection onto the radius, as documented); 3-point arc: ends in either order plus the through point on the created circle; rectangle: bounding box of created edges; polygon: corner centroid, circumradius, side count. Unreadable read-back -> ok with `verified:false` (never a false failure).
- Mismatch: `ok:false`, message plus `data.requested` / `data.actual` (mm). Segments are not deleted. Success keeps old fields, adds `data.actual`, `data.verified`.
- `draw_polyline(points[{x_mm,y_mm}], closed=false, construction=false)`: rejects <2 points, closed with <3, zero-length segments, malformed points (before touching COM). Returns `segments` list; failures list `bad_vertices` (vertex index, requested/actual mm) or partial-creation counts.
- All members used are in sw2017_api_members.txt (ISketchManager.AddToDB/DisplayWhenAdded, ISketchLine/ISketchArc getters, IModelDoc2.GraphicsRedraw2); compat scan passes.

## Files
sw_sketch.py, tests/test_sw2017_sketch_fidelity.py (13 tests), docs/FORK_CHANGES.md, this report.

## Results
Full suite: 495 tests OK. mcp_smoke_client: 169 tools, draw_polyline listed.

## Caveats (live check needed)
- Rectangle/polygon/centerline verification and the AddToDB property get/set via late binding are unverified live. AddToDB creation may skip auto-relations (e.g. no automatic horizontal/vertical or coincident), which is intended.
- The live repro (crowded sketch, 10-point star, 0.6 mm steps) still needs running.

## Revision 1: draw_arc direction=-1
- Original assumption (superseded by Revision 2): a clockwise request reads back with start and end swapped. Live 2017 does NOT swap; it keeps the requested order and reports GetRotationDir=-1.
- `_verify_arc` now takes `direction`; endpoints match as a set (request order or swapped).
- Sweep side is checked with `ISketchArc.GetRotationDir` (in the compat list): it must equal `direction` when ends are in request order, `-direction` when swapped. Unreadable or non-+/-1 value skips the sweep check (no false failure); the value is returned as `actual.rotation_dir`. Whether 2017 reports GetRotationDir with that convention is unverified live (live probe item 7).
- Tests: `ArcDirectionTests` (directions 1/-1 x swapped/unswapped read-back, wrong sweep, unrelated endpoints). Full suite and smoke client pass.

## Revision 2: draw_polygon false mismatch; arc convention
- Live: 2017 CreatePolygon returns N edges plus a construction circle, so `_verify_polygon` saw N+1 sides and a skewed centre.
- New `_line_segments` keeps only GetType==0 segments (unreadable type kept); applied in `_verify_polygon` and `_verify_rectangle`.
- Arc sweep check already expects GetRotationDir == requested direction for unswapped ends (the live convention); swapped ends stay tolerated with the rotation inverted. Docstring and Revision 1 note corrected.
- Tests: `PolygonTests` (6 lines plus a construction circle passes with actual sides 6, centre and radius; wrong radius fails). Suite 500 OK; smoke client 169 tools.

## Revision 3: polygon `inscribed` on 2017
- Live: 2017 CreatePolygon ignores `inscribed` and always puts a corner at the given point.
- `draw_polygon` now computes the corner itself: reach = |point - centre|; corner radius = reach (inscribed) or reach / cos(pi/n) (circumscribed), at the same angle; always passes inscribed=True. `_verify_polygon(segments, centre, circumradius, sides)` verifies against that corner radius in both modes.
- Description now says radius = corner radius when inscribed, apothem when circumscribed, and that a corner always lies in the point's direction (so the edge midpoint is not at the given point).
- `_line_segments`: non-numeric GetType no longer raises (kept, read-back decides).
- Tests added: circumscribed polygon (corner passed, flag True, verified), radius mismatch still fails, rectangle with an extra circle ignored, unreadable-type segment gives verified:false with no `actual`. Suite 515 OK; smoke client 170 tools.
