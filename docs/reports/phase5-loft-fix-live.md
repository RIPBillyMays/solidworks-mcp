# Phase 5 loft fix: offline review and live verification

Script: `tests/live_p5_loft_fix.py` (live, SW 2017, scratch parts, force-closed, never saved; 0 documents open before and after).
Run: `SW_MCP_OUTPUT_ROOT=<repo>\sandbox\loft_probes`, calls through `server.call_tool("loft")`. Raw rows: `sandbox/loft_probes/loft_fix_results.json` (last run only has checks 3c/3f/3g/4b) and the console log.
Profiles: Front plane SA, offset plane "P2" SB at 2.8 mm. Volumes mm3. "est" is average-area x gap, "prism" is the tool's `expected_volume_mm3`.
Unit tests: 652 OK. MCP smoke: 171 tools, handshake OK.

## Live results

| Check | Result | Evidence |
|---|---|---|
| 1 Field case 240x70 R16 -> 234.4x70 R16, default args | PASS | ok; `start_points_mm` [[104,35,0],[101.2,35,2.8]]; counts [8,8]; volume 45875.7 vs est 45875.9 (0.0%); no warnings |
| 2a-2f, 2i Default auto-align with SB/SA drawn from other corners (probe cases 23, 33, 14, rev1/2/3 mixes) | PASS | All pick the same corner and give 45875.7 (was 42942 or 6% low before) |
| 2c Both 3 fillets, different corners (probe 47, was ~6% low) | PASS | ok; 45788.1 vs prism 46029.7 (-0.5%, below threshold, no warning). Profiles are genuinely different shapes (A vertex filleted, B sharp), so a small deficit is expected; was 43402 before |
| 2g 4 fillets vs 3 fillets (probe 44) | PASS | 45923.2 vs prism 45952.8 (-0.06%), same as the old good result |
| 2h Left-aligned profiles (probe 41) | PASS | start points [224,70],[218.4,70]; 45875.8 |
| 2 (180 degree mismatch, formerly null) | PASS | By default auto-alignment removes the mismatch, so it cannot be provoked. With explicit start_points (3a, 3f) it still returns null with a clear hint |
| 3a Explicit 180 degree mismatch (SA near +X+Y, SB -X-Y) | PASS | ok false, no feature, hint present, `start_points_mm` echoed |
| 3b Explicit mismatch +X+Y vs +X-Y, SB drawn mode 3 (was 30583.9) | PASS | ok true; 30583.9 vs 45875.9; `warning: possible twist ... 33.3% below` |
| 3c Explicit matched exact vertices | PASS | 45875.7, no warning |
| 3c-first-run SA pick (224,35,0), 120 mm from the real vertex (104,35), SB rev3 | PASS | 42942.1 (-6.4%), warning fired (reproduces old attempt 23) |
| 3f / 3g Explicit exact-vertex mismatch 180 / 90 degrees (default-drawn SB) | PASS (null + hint) | Both return null with hint; SW refuses instead of twisting here |
| 3d Explicit points far off the sketch (0,500,0) | NOTE | Tool returned ok and a normal loft (45875.7): SelectByID2 returned True off the sketch, so the "pick that misses fails early" path does not trigger for this case. Not a loft failure, but the early-fail claim is not reliable |
| 3e start_points with wrong count | PASS | ok false, clear message |
| 4 Segment count 4 vs 8, default | PASS (better than expected) | Auto-alignment makes it succeed: ok, counts [4,8], 45334.3 vs prism 46183.5 (-1.8%, no warning). Previously null |
| 4b 4 vs 8 with explicit mismatched start points | PASS | null; hint contains `{'SA': 4, 'SB': 8}` |
| 5 closed=true with 2 profiles | PASS | null; hint item (3) says closed=true needs at least 3 profiles |
| 6a/6b/6c Rounded rect built from lines plus arcs: CCW, all arcs CW (draw_arc direction=-1), mixed | PASS | Confirmed via COM that CW arcs keep start/end as drawn and `GetRotationDir` = -1. All three: expected 45875.8936, delta 45875.7277, no warnings |

## Offline review findings

- **start_points validation (`_parse_start_points`, sw_feature.py ~1161):** count and shape checked, floats coerced. Passed to SelectByID2 in metres with mark 1, append for index>0, `nothing()` callout with a pythoncom.Nothing fallback. OK. Only weakness is that SelectByID2 does not return False for far-off points (live check 3d), so "start_points did not land" is mostly dead code. Suggest: document that the pick selects the nearest vertex, or verify the pick distance to the profile's vertices (`info["vertices_mm"]`) and warn if farther than a few mm.
- **Auto-alignment frame:** score = (u+v, v, u) of the model point projected on the FIRST profile's sketch axes, no origin subtraction (fine, a constant per axis). Consistent for parallel planes; the u+v extreme is also well defined for non-parallel planes (a shared model-space direction), but it is not a "corresponding corner" for profiles in rotated or perpendicular planes (projection can degenerate or pick a non-corresponding vertex). Acceptable, the twist check is skipped for non-parallel planes and users can pass start_points. Ties between a filleted corner's two tangent points break on larger v, verified live (both 104,35 and 101.2,35).
- **Twist check maths:** shoelace plus circular-segment terms, chain traversal handles backward segments, `GetRotationDir` -1 handled (verified live, equal result for CW and CCW). Prismatoid with mean mid-section is exact for these cases (est matched to 0.0%). It cannot fail the call: `_volume_mm3` swallows errors and the result stays ok. One residual risk: `_loop_area_m2` is called inside `_profile_info` outside any try (line ~1112 `area = _loop_area_m2(parsed)`); a malformed segment dict would raise out of `loft`. Low probability since entries are constructed in the loop. `_loft_twist_warning` indexes `a0["normal"]` without try, safe because axes dicts come from `_sketch_axes`.
- **Different-shape profiles:** the 5% threshold is loose for the field case (a 6.4% twist was caught, but twists of 3-5% would not be). Fine for now.
- **Fallbacks:** unreadable vertices gives the warning plus origin picks. Null result hint works (live checks 3a, 4b, 5). Wording issue: hint cause (2) "different segment counts" is always printed, even when the counts are equal (3a, 5). Suggest printing cause (2) only when `len(set(counts)) > 1`, and always include the counts.
- **Selection left over after null:** when `feature is None`, `feature_result` does not clear the selection (and the loft branch does not either). Harmless but could pollute a following call; suggest `clear_selection(doc)` in the null branch of `loft`.
- **Compat:** every SW member used (SelectByID2, GetSketchSegments, ConstructionGeometry, GetType, GetStartPoint2, GetEndPoint2, GetCenterPoint2, GetRadius, GetRotationDir [ISketchArc], GetMassProperties2, InsertProtrusionBlend2, InsertCutBlend) is listed in `tools/compat/sw2017_api_members.txt`. No new members.
- **Boss/cut:** `volume_before` skipped for cut or merge=false, twist check is then "not run", with no `twist_check` note set in that branch (only a missing field). Minor.

## Bugs

None blocking. Items above (3d off-sketch pick not rejected, hint wording, selection left after null) are minor suggestions, not fixed. No source edits were made.
