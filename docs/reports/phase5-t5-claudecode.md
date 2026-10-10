# Phase 5 / T5: Claude Code client, live block + hole build

Driver: Sonnet subagent, using only `mcp__solidworks__*` tools. SOLIDWORKS 2017 SP05 (`version` reported by `solidworks_status`: 25.5.0).
Units: every tool takes **millimetres** (and degrees); server converts to metres/radians at the COM boundary. All read tools report mm / mm3 / g.

## Result

- **Geometry: PASS** (all measurements match expected).
- **Save to `sandbox\phase5\`: PASS (re-run after re-registering the server with `SW_MCP_OUTPUT_ROOT=C:\_Projects\solidworks-mcp\sandbox`).** `solidworks_status` confirmed output_root. Saved `C:\_Projects\solidworks-mcp\sandbox\phase5\t5_claudecode_block.SLDPRT`, 61472 bytes. Re-measured after save: volume 14214.6018 mm3, 1 body (bbox 50 x 30 x 10).
- **Overall T5: PASS.**

## Step table

| # | Step | MCP tool + args | Result | COM call underneath | Measured |
|---|------|-----------------|--------|---------------------|----------|
| 1 | Attach | `solidworks_status {}` | ok, attached | `GetActiveObject`, `RevisionNumber` | version 25.5.0, 0 docs open, output_root = Documents\solidworks-mcp |
| 2 | New part | `create_new_document {kind:"part"}` | `Part1` created | `GetUserPreferenceStringValue` -> `ISldWorks.NewDocument` (sw_file.py:210) | type part, path "" |
| 3 | Check planes | `list_reference_planes {}` | Front/Top/Right Plane | feature tree walk | English names |
| 4 | Sketch on Front | `create_sketch {plane:"front", name:"BlockProfile"}` | opened | `SelectByID2("Front Plane","PLANE")` -> `SketchManager.InsertSketch(True)` (sw_sketch.py:139) | sketch open |
| 5 | Rectangle centred on origin | `draw_rectangle {x1_mm:-25,y1_mm:-15,x2_mm:25,y2_mm:15}` | 4 segments | `SketchManager.CreateCornerRectangle` (sw_sketch.py:296) | 4 segments |
| 6 | Close sketch | `close_sketch {}` | closed | `InsertSketch(True)` toggle | - |
| 7 | Boss extrude | `boss_extrude {depth_mm:10, sketch_name:"BlockProfile", name:"BlockBoss"}` | feature `BlockBoss` | `IFeatureManager.FeatureExtrusion3` (sw_feature.py:138) | bbox 50 x 30 x 10, min (-25,-15,0), max (25,15,10) |
| 8 | Find top face | `list_faces {normal:[0,0,1]}` | face 4, area 1500 | `GetFaces` + normal filter | point (0,0,10), 1500 mm2 |
| 9 | Sketch on top face | `create_sketch {face_index:4, name:"HoleProfile"}` | opened on face 4 | `Select4` on face -> `InsertSketch(True)` | sketch open |
| 10 | Circle d10 | `draw_circle {x_mm:0,y_mm:0,radius_mm:5}` | 1 segment | `SketchManager.CreateCircleByRadius` (sw_sketch.py:276) | r=5 (sketch-local origin = face centre = part origin XY) |
| 11 | Close sketch | `close_sketch {}` | closed | `InsertSketch(True)` | - |
| 12 | Through-all cut | `cut_extrude {end_condition:"through_all", sketch_name:"HoleProfile", name:"CenterHole"}` | feature `CenterHole` (type ICE) | `IFeatureManager.FeatureCut4` (sw_feature.py:189, falls back to FeatureCut3) | see below |
| 13 | Mass | `get_mass_properties {}` | ok | `IModelDocExtension.GetMassProperties2(2, status, False)` (sw_inspect.py:238) | **volume 14214.6018 mm3** (expected 14214.6, 0.0000% error), area 4757.08 mm2, mass 14.2146 g (density 1.0 default, no material), CoM (0, 0, 5) mm |
| 14 | Bbox | `get_bounding_box {}` | ok | `GetPartBox(True)` (sw_inspect.py:213) | size 50 x 30 x 10 mm |
| 15 | Bodies | `list_bodies {}` | 1 body | `GetBodies2` | 1 solid body, named "CenterHole" |
| 16 | Features | `list_features {}` | tree OK | feature walk | BlockProfile, BlockBoss, HoleProfile, CenterHole in order |
| 17 | Hole check | `list_faces {surface_type:"cylinder"}` | 1 cylinder | face enumeration | r=5, axis (0,0,1), area 314.1593 = 2*pi*5*10 (full 10 mm depth, so through), point (5,0,5) so centred at X=0,Y=0; CoM x,y = 0 confirms |
| 18 | Errors | `check_errors {}` | no problems | rebuild + `GetWhatsWrong` | 0 problems |
| 19 | Save | `save_document {path:"C:\\_Projects\\solidworks-mcp\\sandbox\\phase5\\t5_claudecode_block.SLDPRT"}` | **refused**: "output path must be under C:\Users\Zach Tonsmeire\Documents\solidworks-mcp" | `validated_output_path` (sw_file.py:61), never reached SaveAs | no file written |
| 20 | Modal check | `get_active_document_info {}` | answered immediately | `GetTitle`/`GetPathName` | COM responsive, so no blocking modal; doc `Part1`, dirty=true |

## T5 verdict

- Volume 14214.6018 mm3 vs 14214.6 expected: PASS (< 0.001%).
- Bbox 50 x 30 x 10: PASS. Hole d10, centred, through 10 mm: PASS. 1 body, 0 rebuild errors, no dialogs: PASS.
- File saved to sandbox: PASS (61472 bytes; volume 14214.6018 mm3 and 1 body re-measured after save).
- Whole build took 17 tool calls, no retries, no failures.

## Observations / rule candidates

1. **Output root vs sandbox mismatch (blocker for save).** The server's output sandbox defaults to `~/Documents/solidworks-mcp`; ADR-0005 wants everything under repo `sandbox/`. Fix without touching source: set `SW_MCP_OUTPUT_ROOT=C:\_Projects\solidworks-mcp\sandbox` in the `env` of the `solidworks` MCP registration (`claude mcp add ... -e SW_MCP_OUTPUT_ROOT=...` or `.mcp.json`) and restart the client; then re-run only step 19 on the still-open `Part1`. Candidate rule: live tests must register the server with `SW_MCP_OUTPUT_ROOT` pointing to `sandbox/`. `solidworks_status` already returns `output_root`, so the AI can check it before building.
2. **Body is named after the last feature.** `list_bodies` shows body "CenterHole" (SW names a body after its latest feature), so body name is not a stable identifier. Rule candidate: identify bodies by index/bbox, not name.
3. **Face indices are volatile.** `list_faces` indices change after every feature (hole added a 7th face). Rule candidate (extends existing "re-list after geometry change"): always call `list_faces` with a `normal` / `surface_type` filter immediately before selecting; never reuse an index.
4. **"Top face" is ambiguous.** Sketching on Front Plane extrudes along +Z, so the "top" (largest +Z) face is Z=10, but SolidWorks "Top Plane" is XZ. Rule candidate: state the axis convention in the plan (here: extrude along +Z from Front Plane; top face = +Z normal face), and verify with `list_faces normal=[0,0,1]`.
5. **`list_faces` shows two normals.** `normal` (0,0,1) and `surface_normal` (0,0,-1) differ for the same face (face orientation vs underlying surface). The `normal` filter uses the outward one, which is what's wanted; models could be confused by `surface_normal`. Rule candidate: trust `normal`, ignore `surface_normal`.
6. **Sketch on a face is sketch-local.** Centre (0,0) worked here only because the face centre coincides with the part origin XY. Rule candidate: after sketching on a face, confirm the sketch origin vs model coordinates (e.g. via cylinder `point_mm` after the cut) rather than assuming.
7. **Default material "not specified", density 1.0 g/cm3,** so `mass_g` equals volume/1000. Volume is the reliable check; mass is meaningless until `set_material`.
8. **Unit surprise: none.** All parameters mm/deg; naming convention `*_mm`, `*_deg` made this unambiguous. The `end_condition: through_all` ignores `depth_mm` but the response still echoes `depth_mm: 10`, which is cosmetic and could mislead.
9. **Deferred-tool loading cost one extra round-trip** (ToolSearch select) before any call; a short batch load of the ~20 core tools worked fine.
10. **Verification that worked well:** cylinder-face area (314.159) as an independent proof of through-depth, and CoM x,y = 0 as proof of centring, in addition to total volume.
