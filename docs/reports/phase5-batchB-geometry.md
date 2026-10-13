# Phase 5 Batch B: geometry (offline build)

Offline only; no live SOLIDWORKS. Full suite 292 tests OK; MCP smoke lists 146 tools incl. all 16 new ones. Every API member used is in `sw2017_api_members.txt` (parameter lists read from the installed 2017 typelib, enums checked in `tests/test_sw2017_batchB_geometry.py`). No commit.

## Files
- `solidworks_mcp/sw_feature.py` (additive, end of file): `hole_wizard`, `cosmetic_thread`, `fillet_variant` (variable/face/full_round), `chamfer_vertex`. Existing `chamfer` already covers distance_distance.
- `solidworks_mcp/sw_body.py` (new, one import line in `server.py`): `create_reference_point`, `create_coordinate_system`, `combine_bodies`, `split_body`, `move_copy_body`, `scale_part`, `mirror_body`, `delete_body`, `intersect_bodies`, `create_dome`, `create_helix` (incl. spiral), `wrap_sketch`.
- `tests/test_sw2017_batchB_geometry.py` (34 tests).
- Constants use `Final` annotations so `test_sw2017_enums`' bare-assignment audit does not demand edits to that shared file.

## Not done / fenced
- Nothing fenced: all members exist. Several are unverified (below) and fail with a clear message rather than silently.
- `create_plane`/`create_axis` extension not done (`sw_refgeom.py` is outside the scope list; create_plane already has offset/angle/midplane/three_points/parallel_through_point). Candidate for a later pass.
- Mirror body also reachable via existing `mirror_feature(mirror_body=true)`; `mirror_body` is the body-indexed form.

## FORK_CHANGES lines
- `solidworks_mcp/sw_feature.py`: added hole_wizard (HoleWizard5), cosmetic_thread (InsertCosmeticThread3), fillet_variant (FeatureFillet3 types 1/2/3), chamfer_vertex (InsertFeatureChamfer type 3); imports `Final`, `double_array`, `select_at_point`.
- `solidworks_mcp/sw_body.py` (new): reference point/coordinate system, combine/split/move-copy/scale/mirror/delete/intersect body, dome, helix/spiral, wrap.
- `solidworks_mcp/server.py`: one import line for `sw_body`.

## Live verification checklist (serial, sandbox part, measure each by volume/body count/feature tree)
Block 1, likely fine:
1. `create_reference_point` face_center, arc_center, along_curve (distance; percentage: confirm 25 means 25%, code sends 0.25; evenly count 4), intersection, sketch_point. Check via list_features and measure to the point.
2. `combine_bodies` add/subtract/common on two overlapping boxes: volumes and body count (`list_bodies`).
3. `delete_body` keep=false and keep=true; `move_copy_body` translate (bbox shift), rotate (about pivot), copy count 3 (body count +3); `scale_part` uniform 2 (volume x8), non-uniform, about origin vs centroid; `mirror_body` merge false/true; `create_dome` (volume change, reverse, elliptical); `create_helix` all four defined_by, tapered, spiral (check pitch/height via feature params or bbox).
4. `chamfer_vertex` equal and unequal distances (volume removed = tetrahedron d1*d2*d3/6).
Block 2, unverified argument conventions; probe and adjust the named constant:
5. `hole_wizard`: **Value1..12 slot mapping is a guess** (V1/V2 = cbore dia/depth or csink dia/angle rad, V3 = thread depth). Make one counterbore, one countersink and one tap by hand in the UI, read the definition (GetDefinition on the hole feature) or compare geometry, then correct `_hole_values` or use `raw_values_mm`. Also verify: fastener index per standard, size strings ("M6x1", "1/4-20"), `Length` arg (code passes depth), cosmetic thread present for tap, one feature per point, thread_class.
6. `cosmetic_thread`: standard index and standard_type/size strings as the UI shows.
7. `fillet_variant`: variable (PointRadiusArray order and Options=1|4; unverified, may need Radii array or vertex selection), face fillet (marks 1/2 from `swSimpleFilletWhichFaces_e`), full round (marks 3/4/5; alternative guess 1/2/4 or 512 for center). Constants `FILLET_MARK_*` are the single place to change.
8. `create_coordinate_system`: marks 1/2/4/8 (`COORD_MARK_*`), direction picks; fallback `CreateCoordinateSystem` with objects.
9. `split_body`: `PreSplitBody2` return type (code expects an array of resulting bodies; `PostSplitBody(bodies, consume, empty, empty)`). Check body count after.
10. `intersect_bodies`: `PreIntersect2(cap, 0)` RegionType meaning and `PostIntersect(empty, merge, consume)`; empty exclusion list may need an explicit empty array.
11. `wrap_sketch`: marks sketch=1, face=2; mesh_factor default 4; thickness sign for deboss.
12. Each new feature tool under `dialogs_suppressed()`: confirm no modal dialog on a bad selection (feature returns None, tool reports failure).
