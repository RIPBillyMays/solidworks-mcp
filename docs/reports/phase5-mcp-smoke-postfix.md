# Phase 5 MCP smoke test (post-fix, restarted server)

| # | Step | Result | Evidence |
|---|------|--------|----------|
| 1 | Status check | PASS | output_root `C:\_Projects\solidworks-mcp\sandbox`, 0 docs open, SW version 25.5.0. draw_polyline, activate_document, delete_sketch_segment all present. |
| 2 | Polyline star + extrude | PASS | Shoelace area 1058.0138 mm2 -> expected 10580.138 mm3; measured 10580.1381 (0.0000%). `direction_vector` [0,0,1], `volume_delta_mm3` 10580.1381. Polyline returned 10 segments, verified:true. |
| 3 | Sketch fillet + delete segment | PASS | Rect 40x20 on Top, fillet R3 -> 4 arcs + 4 lines (8). delete_sketch_segment index 0 -> segments_before 8, after 7; list_sketch_segments confirms 7. close_sketch ok. |
| 4 | Loft | PASS | Part2: SA (Front, R16 fillets), plane P2 +2.8 mm, SB (P2). Loft ok, no twist warning. Volume 45875.7277 vs 45876 expected (-0.0006%); tool's own expected 45875.8936. `start_points_mm` [[104,35,0],[101.2,35,2.8]]. |
| 5 | activate_document | PASS | Part1 then Part2; `active_document` read back correctly each time. |
| 6 | Cleanup | PASS | Both closed; list_open_documents -> 0 documents. Nothing saved. |

Overall: PASS.

## Friction as an MCP user
- close_document refuses dirty unsaved docs; `force=true` needed to discard (expected, but a scratch doc cannot be closed without it).
- create_plane `selection.planes` accepted "front" fine; plane naming via `name` worked.
- draw_rectangle only returns corners; fillet needs corner coords re-stated by the caller (fine).
- The rectangle in step 3 was sketched on Top, whose sketch Y maps to -Z (create_sketch reports this; good).
- No surprising result text.
