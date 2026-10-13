# Phase 5 loft investigation (finding #16)

Script: `tests/live_p5_loft_probe.py` (live, SW 2017, one scratch part per attempt, force-closed, never saved).
Profiles: Front Plane sketch SA plus an offset plane "P2" 2.8 mm away, sketch SB. Rounded rectangles come from `draw_rectangle` plus `sketch_fillet corners`.
"Tool" means `server.call_tool("loft")` with the current code. "COM" means a direct `InsertProtrusionBlend2` call with the same 18 args as the tool and `SelectByID2(name, "SKETCH", x, y, z, ..., mark 1)`.
Volumes in mm3 against the average-area x gap estimate. The estimate is accurate to about 0.01 percent for a correct loft.

| Attempt | Settings | Result | Volume (est) |
|---|---|---|---|
| 1 | Tool, 240x70 R16 -> 234.4x70 R16, both centred, drawn the same way | OK | 45875.7 (45875.9) |
| 2 | Tool, 234.4x70 R16 -> 232x67.6 R14.8 | OK | 44354.6 (44356.8) |
| 3 | COM, tool flags, pick at origin | OK | 45875.7 |
| 4 | COM, picks at the +X+Y tangent point (x = w/2 - r, y = 35) on both | OK | 45875.7 |
| 5 | COM, pick +X+Y on SA, -X-Y on SB (180 degree start mismatch) | FAIL (null, no feature, whats_wrong empty) | 0 |
| 6 | Tool, no fillets | OK | 46491.2 |
| 7 | Tool, 240 -> 238, R16 | OK | 46228.5 |
| 8 | Tool, identical profiles | OK | 46424.6 |
| 9 | Tool, order SB,SA | OK | 45875.7 |
| 10 | COM, KeepTangency true | OK | 45875.8 |
| 11 | COM, ForceNonRational true | OK | 45875.7 |
| 12 | COM, Closed true (2 profiles) | FAIL (expected) | 0 |
| 13 | COM, merge false | OK | 45875.7 |
| 14 | Tool, SB fillet order rotated | OK | 45875.7 |
| 15 | Tool, gap 10 mm | OK | 163842.0 (163842.5) |
| 16 | Tool, 70 -> 69 height | OK | 45545.0 |
| 17 | Tool, R16 -> R15.9 | OK | 45879.6 |
| 21 | Tool, SB rectangle drawn corner mode 1 (reversed corners) | OK | 45875.7 |
| 22 | Tool, SB drawn mode 2 | OK | 45875.7 |
| 23 | Tool, SB drawn mode 3 (starts at another corner) | OK but wrong | 42942.1 (45875.9), twisted |
| 31 | Tool, SA drawn mode 1 | OK | 45875.7 |
| 32 | Tool, SA drawn mode 2 | OK | 45875.7 |
| 33 | Tool, SA drawn mode 3 | OK but wrong | 42941.1, twisted |
| 24 | COM, SB mode 3, matched picks (as 4) | OK, correct | 45875.7 |
| 25 | COM, SB mode 3, SA +X+Y, SB -X-Y | FAIL | 0 |
| 26 | COM, SB mode 3, SA +X+Y, SB +X-Y | OK but wrong | 30583.9 (45875.9), badly twisted |
| 27 | COM, SB mode 3, SA +X+Y, SB -X+Y | OK but wrong | 30583.9 |
| 41 | Tool, both profiles left aligned at x=0 | OK | 45875.8 |
| 42 | Tool, SB right aligned | OK | 45875.8 |
| 43 | Tool, A sharp (4 segments), B R16 (8 segments) | FAIL (null) | 0 |
| 44 | Tool, A 4 fillets, B 3 fillets | OK | 45923.2 |
| 45 | Tool, A 3 fillets, B 4 fillets | OK | 45923.3 |
| 46 | Tool, both 3 fillets, same corners | OK | 46029.6 |
| 47 | Tool, both 3 fillets, different corners | OK but wrong | 43402.5 (about 6 percent low) |

## Findings

- **The exact field failure did not reproduce.** The tool loft of 240x70 R16 -> 234.4x70 R16 succeeded 6 of 6 times, whatever the merge, tangency, non-rational, gap or draw-order setting.
- **Start-point mismatch produces the failure class.** With an unchanged call, SW returns null and leaves no feature in the tree when the connector start points are roughly 180 degrees apart (attempts 5 and 25). It silently builds a twisted loft with 6 to 33 percent less volume when they are 90 degrees or less apart (23, 26, 27, 33, 47). Pick points choose the start, and matched picks fix it (24).
- **Segment-count mismatch can also fail.** A sharp 4-segment profile to an 8-segment rounded profile returned null (43).
- **No difference was made by** the tangency flags, KeepTangency, ForceNonRational, merge, closed, plane versus face, or the extent of the dimension change. `Closed=true` fails for 2 profiles.
- **Failure feedback is empty.** After a failed loft, `whats_wrong` is empty, no errored feature remains, and there is no error code. The only signal is a null return. For successful twisted lofts the tool reports ok with no warning.

## Root cause

The root cause is that the tool gives SW no connector control. It selects every profile with pick point (0,0,0), so SW picks each sketch's own default start vertex.

The default start depends on how the sketch was built (first segment, corner order, fillet history). If the two sketches' starts do not correspond, the loft is either null (large mismatch) or twisted (partial mismatch).

Confidence: high that start mismatch is a real cause of the null return. It reproduces by hand with a 180 degree mismatch. Medium that it explains the exact field sketches, because I could not obtain the field sketches' start vertices. A segment-count mismatch is a secondary possible cause.

## Fix proposal for `loft` (`sw_feature.py`)

1. **Add a `start_points` argument.** It is an optional list with one `{x_mm, y_mm}` entry per profile, in each sketch's own coordinates.
   - Convert each entry to model coordinates with the sketch transform. This is the same logic `create_sketch` uses to report `sketch_x_axis`, `sketch_y_axis` and `origin`.
   - Select with `extension(doc).SelectByID2(name, "SKETCH", x, y, z, append, 1, nothing(), 0)` instead of `require_selection`'s (0,0,0) pick.
   - SelectByID2 returns False if the point is off the sketch, so the tool should fail early with that message.
2. **Add an auto start point as the default.** The profiles run in different planes, so use the same model-space direction for every profile.
   - Take each sketch's segment vertices, with `list_sketch_segments` data in model coordinates.
   - Choose the vertex nearest the extreme in a fixed direction, for example maximum X then maximum Y.
   - Use the same rule for all profiles.
   - This reproduces the "matched pick" behaviour of attempts 4 and 24.
3. **Validate the result.**
   - After the loft, compare the part volume delta with `mean(profile areas) x spacing x 0.9`. Compute the areas from the closed-profile segments.
   - If it is more than about 5 percent low, report `ok: true` with a `warning: possible twisted loft, set start_points`. Attempts 23, 26, 27 and 47 would all be caught.
   - If this is too much for the tool, expose `bodies_volume_before/after` in the result so the caller can check.
4. **Improve null-return reporting.** `feature_result` can only say "did not create".
   - Add loft-specific hints to the message: the profiles' segment counts (from `list_sketch_segments`), the start points used, and "start points may be mismatched, pass start_points".
   - Detect a segment-count difference up front and add it to the message.
   - Add `closed=true` with fewer than 3 profiles as an explicit refusal.
5. **Keep the other args as they are.** The tangency flags make no difference in these cases, so they do not need to change.

Orchestrator note: no source was edited. The only files created are `tests/live_p5_loft_probe.py` and this report.

## Fix (implemented offline, not yet live-verified)

`loft` in `solidworks_mcp/sw_feature.py` (boss and cut share the code):

- **`start_points`:** optional, one `[x, y, z]` model-space point in mm per profile. Each is the `SelectByID2` pick (mark 1). A pick that misses fails the call before the loft runs.
- **Default auto-alignment:** each profile's line and arc endpoints are read and mapped to model space with `_sketch_axes` (fix #15). Every profile picks the vertex with the max of `u + v` along the first profile's sketch axes. Ties (the two tangent points of a fillet) break toward larger `v`. The picks are reported as `start_points_mm`. If vertices cannot be read, the old origin pick is used and `warnings` says so.
- **Null result:** `data.hint` and the message name start-point mismatch, segment-count mismatch (with `profile_segment_counts`) and `closed=true` with fewer than 3 profiles.
- **Twist warning:** for a merged boss loft of two parallel planar profiles, the volume delta is compared with `h/6 (A1 + 4 Am + A2)` (Am is the mean of A1 and A2). Areas come from the closed line/arc chain of each sketch (Green's theorem), because no compat member gives a sketch region area. More than 5% low adds `warning: possible twist` to `data.warnings`, and the call still returns ok. Other cases set `data.twist_check` to a "skipped" note.
- **Compat:** no new SOLIDWORKS members. It uses `SelectByID2`, `ISketch.GetSketchSegments`, `ISketchSegment.ConstructionGeometry/GetType`, `ISketchLine/Arc.GetStartPoint2/GetEndPoint2/GetCenterPoint2/GetRadius` and `GetMassProperties2`, all in `sw2017_api_members.txt`.
- **Tests:** `tests/test_sw2017_loft.py`.
- **Open live check:** sketch arcs are assumed to run counter-clockwise from start to end for the area estimate. Re-run `tests/live_p5_loft_probe.py` cases 23, 26, 33 and 47 through the tool.

FORK_CHANGES text: **`loft` (finding #16):** new `start_points` argument. Profiles are now picked at matching auto-aligned vertices instead of (0,0,0). Reports `start_points_mm` and `profile_segment_counts`. A null result carries a hint. A possible-twist volume warning is added. Tests in `tests/test_sw2017_loft.py`.
