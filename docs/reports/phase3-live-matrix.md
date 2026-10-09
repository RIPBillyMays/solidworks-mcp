# Phase 3 live matrix: SOLIDWORKS 2017 SP5 smoke test

- **Date:** 2026-10-08
- **SOLIDWORKS:** revision `25.5.0` (2017 SP5), attached to the instance Zach launched
- **Run folder:** `C:\_Projects\solidworks-mcp\sandbox\run-20261008-221839` (results.json, exported files, screenshots)
- **Command:** `$env:SW_MCP_OUTPUT_ROOT="C:\_Projects\solidworks-mcp\sandbox"; .venv\Scripts\python.exe tests\live_sw2017_smoke.py`
- **Script:** `tests/live_sw2017_smoke.py` (calls the tool handlers directly, every case verified by measurement, 60 s watchdog per case)
- **Offline suite after the run:** `unittest discover -s tests` = 74 tests OK (the live script is not collected)

This report comes from one complete, clean run of the final script (run `20261008-221839`). Three earlier runs
(`run-20261008-214454`, `-215915`, `-220900`) were script-debugging iterations and are not reported.

## Summary

- **T3 core chain: PASS** (all 11 steps).
- Cases: {'PASS': 96, 'SILENT-FAIL': 2, 'FAIL': 3, 'UNVERIFIED': 2}. No HANG, no modal dialog seen.
- Tools (92 registered, worst status per tool): {'PASS': 86, 'FAIL': 3, 'SILENT-FAIL': 2, 'UNVERIFIED': 1}. All 92 were exercised; the 2 `demo_*` tools are opt-in and NOT-RUN.
- Slowest cases: 2.2 topology lists 27.17s, T3.8 fillet 22.93s, 4.3 set_construction_geometry 21.76s, 4.4 dimension / relation / status 20.33s, 4.6 sketch edit sketch 17.14s, 4.2 draw_spline 16.54s. Headroom under the 60 s watchdog is fine.
- Environment facts: default part template `C:\ProgramData\SolidWorks\SOLIDWORKS 2017\templates\Part_Metric_MM.prtdot` (preference id 8 resolves, so the Phase 2 id fix works; the disk-scan fallback would have picked `Part.prtdot`); document linear units **mm** (matches R-008); default drawing template `C:\ProgramData\SolidWorks\SOLIDWORKS 2017\templates\Drawing.drwdot`.

### Incident to disclose (my mistake)
At the start of the first run `baseline_docs` was `['Part1', 'Part2', 'Part3']`: three unsaved documents were already open in the
session although the brief said none. Later, a scratch diagnostic of mine (`sandbox/scratch_topo.py`) called `CloseDoc` on **every**
open document, which closed those three **without saving**. If they held anything it is gone. The final script only closes
documents whose titles were not in the baseline, and the final run's baseline was empty (`docs_remaining = []`).

## T3 core chain

| Step | Tools | Expected | Measured | Status |
| --- | --- | --- | --- | --- |
| T3.1 new part | create_new_document, get_active_document_info | part created from default template, mm | title=Part49 template=C:\ProgramData\SolidWorks\SOLIDWORKS 2017\templates\Part_Metric_MM.prtdot units=mm | PASS |
| T3.2 reference planes | list_reference_planes | 3 planes | planes=['Front Plane', 'Top Plane', 'Right Plane'] axes=[] | PASS |
| T3.3 sketch rectangle | create_sketch, draw_rectangle, list_sketch_segments | 4 lines, 20 x 10 at origin | 4 lines, extents x 0..20 y 0..10, segments_added=4 | PASS |
| T3.4 close sketch | close_sketch, list_sketches | sketch listed, none open | sketches=['T3_Base'] open=False | PASS |
| T3.5 boss extrude | boss_extrude, get_bounding_box, list_bodies | volume 1000 mm3 +-0.1%, 1 body, bbox 20x10x5 | volume=1000.0 bodies=1 bbox=[20.0, 10.0, 5.0] | PASS |
| T3.6 sketch circle | draw_circle | 1 circle r=2 at (10,5) | circle r=2 at (10,5) | PASS |
| T3.7 cut extrude | cut_extrude | volume 937.168 (1000 - pi*4*5), more faces | volume=937.1681 expected=937.168 faces 6->7 | PASS |
| T3.8 fillet | fillet, list_edges | volume 932.876, faces +4 | volume=932.8761 expected=932.876 faces 7->11 | PASS |
| T3.9 mass properties | get_mass_properties | volume 932.876, area 727.40, COM (10,5,2.5) | volume=932.8761 area=727.3982 (exp 727.40) com=[10.0, 5.0, 2.5] mass_g=0.932876 inertia_keys=False | PASS |
| T3.10 save | save_document | file exists, size > 0, doc re-pathed, overwrite refused | T3_core.sldprt 75866 bytes; overwrite refused: RuntimeError: Refusing to overwrite existing output: C:\_Pro | PASS |
| T3.11 export STEP | export_document | file > 1 KB, ISO-10303-21 header, overwrite refused | T3_core.step 31521 bytes header ok; overwrite refused: RuntimeError: Refusing to overwrite existing outpu | PASS |

Verdict: **PASS**. Geometry matches closed-form values to better than 0.001%.

## "Phase 3: verify live" sites

`grep "Phase 3: verify live" solidworks_mcp/` finds five sites. Note the brief called the fifth "detail view (~755)": line 755 of
`sw_drawing.py` is actually the **tangent-edge** call in `set_drawing_view`; `insert_detail_view` carries no marker. Both are reported.

| # | Site | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | `sw_feature.py:244` revolve mid-plane (`Dir1Type=6`, `single_direction=False`) | **PASS** | volume=12566.3706 (quarter=12566.4); bbox z -21.21..21.21 (symmetric, +-21.21 expected); x 7.07..30.00. 90 degree mid-plane revolve gives exactly one quarter of the full solid and is symmetric about the sketch plane, so mid-plane took effect. |
| 2 | `sw_drawing.py:440` drawing display mode + `Edges=True` | **PASS** | `shaded_with_edges` gave +1 view 'Drawing View4' scale=0.5 GetDisplayMode=3 EdgesInShadedMode=True. So `SetDisplayMode3(False, 3, False, True)` shows edges; the `swSHADED_EDGES=7` alternative is not needed. `hidden_lines_removed` reads back mode 2 (pos=(320.0,70.0) scale=0.4 mode=2 tangent=2). |
| 3 | `sw_drawing.py:584` section view options (`0`, `64` fasteners, `depth_mm`) | **PASS** for creation, **UNVERIFIED** for `depth_mm` | +1 section view 'Section View A-A' type=section scale=2.0 pos=[244.5, 110.69] (cut line at x=94.5, y 94.7..126.7). The section view is created with type `section`, parent's scale. With `depth_mm=3` a second section (B-B) is created, but the API gives no way to measure whether the depth was honoured (Partial=16 question stays open; check the screenshot `DRW_screenshot.png` by eye). |
| 4 | `sw_drawing.py:755` `SetDisplayTangentEdges2` | **PASS** | `tangent_edges="visible"` reads back `GetDisplayTangentEdges2 = 2` (pos=(320.0,70.0) scale=0.4 mode=2 tangent=2). |
| 4b | (extra) `insert_detail_view` style/show-type args | **PASS** | +1 detail view 'Detail View D (4 : 1)' scale=4.0 pos=[360.0, 250.0]. Detail view type `detail`, scale reads back 4.0 as requested. |
| 5 | `sw_inspect.py:368` `set_view` shaded-with-edges via `ActiveView.DisplayMode = 5` | **PASS** | DisplayMode 3 -> 5 (5 = shaded with edges); 9 named views accepted. Preset to 3, tool call moved it to 5, so the property set takes effect. |

## Phase 4 candidates (FAIL / SILENT-FAIL)

| # | Tool | Status | Evidence | Best guess at cause |
| --- | --- | --- | --- | --- |
| 1 | `chamfer` mode `equal_distance` (the default) | SILENT-FAIL | chamfer feature created but volume 48000.0 != 47960.0 (faces 6 -> 6); no geometry change. A feature named `Chamfer` appears in the tree, `check_errors` is clean, geometry is unchanged. `angle_distance` 45 degrees (-40 mm3, +1 face, case 3.3b) and `distance_distance` (-60 mm3) work; confirmed by a scratch diagnostic. Propagate on/off and a top edge instead of a vertical edge behave the same. | `sw_feature.py:330` `InsertFeatureChamfer` called with type `CHAMFER_EQUAL_DISTANCE = 16` (`sw_core.py:103`). 16 is `swChamferEqualDistance` but 2017's `InsertFeatureChamfer` apparently builds nothing for it. Fence: map `equal_distance` to `angle_distance` with 45 degrees. |
| 2 | `rib` default arguments | FAIL | rib: SOLIDWORKS did not create the rib. Check that the required selection was valid. Neither extrusion direction reached material: check that the profile spans between two existing faces. Same sketch with `reverse_material=True` adds exactly 800.00 mm3 (case 5.5b). | `sw_feature.py:422-445`: the automatic retry only flips `normal_to_sketch`, never `reverse_material`, so a corner gusset whose material side is the non-default one never builds. Retry both combinations. |
| 3 | `insert_component` absolute position | SILENT-FAIL | component inserted at (0,0,0) has origin [-10.0, -5.0, -2.5]; the x/y/z arguments do not place the component origin. Relative offsets are right (second part at +100,0,+20 reads back exactly). The part's bbox centre is (10,5,2.5), so the x/y/z arguments place the component's bbox centre or centre of mass, not its origin. | `sw_assembly.py:116-119` `AddComponent5` coordinates. Either document it, or read the transform after insert and translate by the difference. |
| 4 | `auto_dimension_view` | FAIL | auto_dimension_view: Auto-dimensioning added nothing (status 1). `swAutodimStatus_e` 1 is `BadOptionValue`. `insert_model_annotations` on the same drawing does import 2 dimensions (PASS), so the drawing itself is fine. | `sw_drawing.py:873` `IDrawingDoc.AutoDimension` is the sketch auto-dimension (needs an active sketch, own option enums) not a view-level DimXpert. The tool premise looks wrong; fence it or find a view-level route. |
| 5 | `export_document` `.3mf` | FAIL (false negative) | export_document: SOLIDWORKS failed to export the document. (file on disk afterwards: True, 20001 bytes). The file is a valid 3MF zip (`3D/3dmodel.model`, thumbnail). No dialog appeared. | `sw_file.py:96-104` `_save_as` treats any non-zero `errors` or a false return as failure; 2017 writes the file but reports a nonzero error/warning code. Inspect the codes and accept when the file is non-empty and the code is a warning only. STL (15284 bytes) passed. |

Not failures but worth knowing:
- `insert_centerlines` default path on a projected view: handler ok, no annotation gained (UNVERIFIED; that view shows the hole only as hidden lines). `insert_center_marks` on the front view gained a real center-mark annotation (2 -> 3, PASS).
- After the coincident mate the solver moved the free component 88 mm along x (`T3_core-2` origin x 90 -> 2) as well as aligning z. That is solver behaviour for an under-constrained component, not a tool defect.
- `get_mass_properties` returns no inertia tensor on 2017 (`moments_of_inertia_kg_m2` absent), as the catalog predicted.
- `measure` works on 2017 (catalog item 3 predicted failure): face gap 5.0, edge 18.0, face area 186.58 all correct.
- `draw_polygon` and `draw_slot` also add one construction segment each (circle / centreline); normal SOLIDWORKS behaviour.
- `insert_standard_views` creates 3 views (front is typed `named`, the other two `projected`), automatically scaled 2.0 on a 1:1 sheet.
- `draft` default (`reverse=False`) tapers outward as its description says (9481.46 vs 8000).
- Negative cases with no document raise `RuntimeError("SOLIDWORKS has no active document...")`, which the server turns into `ok:false`.

## Dialogs and preferences

No modal dialog and no hang occurred anywhere in the run. Specifically no prompt from: `add_dimension` (input-dimension preference 10 suppressed by the tool, used on 4 dimensions, never over-defined), STL export, 3MF export, `open_document` of a sandbox file, `insert_component`, section/detail/projected views, or `create_drawing`.

## Full matrix (92 tools)

Status is the worst over the cases that exercise the tool (`PASS/FAIL` means some cases passed and some failed). Case ids refer to `results.json`.

| Tool | Status | Measured evidence | Notes | Cases |
| --- | --- | --- | --- | --- |
| activate_drawing_view | PASS | sketch opened in 'Drawing View1', 1 segment drawn, closed |  | 8.10 |
| activate_sheet | PASS | sheets=['Sheet1', 'Sheet_Two'], reactivated Sheet1 |  | 8.2 |
| add_dimension | PASS | status under_defined->under_defined; horizontal ok; dim SK_Len@SK_Draw@Part51.Part: 40 -> 25 |  | 4.4, 6.1 |
| add_mate | PASS | mates 0 -> 1 {'name': 'Coincident1', 'mate_type': 'coincident'}; origins after mate [('T3_core-2', [2.0, -5.0, -2.5]), ('T3_core-1', [-10.0, -5.0, ... |  | 7.4 |
| add_note | PASS | note annotations (all views) 67 -> 68 |  | 8.15 |
| add_relation | PASS | status under_defined->under_defined; horizontal ok; dim SK_Len@SK_Draw@Part51.Part: 40 -> 25 |  | 4.4 |
| add_sheet | PASS | sheets=['Sheet1', 'Sheet_Two'], reactivated Sheet1 |  | 8.2 |
| auto_dimension_view | FAIL |  | [8.12 auto_dimension_view] auto_dimension_view: Auto-dimensioning added nothing (status 1). | 8.12 |
| boss_extrude | PASS | volume=1000.0 bodies=1 bbox=[20.0, 10.0, 5.0] |  | 3.1, 5.5a, T3.5 |
| capture_screenshot | PASS | T3_screenshot.png 118824 bytes 800x496 stddev=88.7 |  | 2.8, 8.18 |
| chamfer | SILENT-FAIL/PASS | volume 48000.0 -> 47960.0 (expected 47960.0); faces +1 | [3.3 chamfer] chamfer feature created but volume 48000.0 != 47960.0 (faces 6 -> 6); no geometry change | 3.3, 3.3b |
| check_errors | PASS | no problems; force_all rebuild ok; volume stable 932.8761 |  | 2.6 |
| circular_pattern | PASS | volume=27520.3516 expected=27520.35 |  | 5.8 |
| close_sketch | PASS | sketches=['T3_Base'] open=False |  | 3.12, 4.12, 4.5, T3.4 |
| convert_entities | PASS | segments 0 -> 8 |  | 3.13 |
| create_axis | PASS | axes 0->1: ['Block_Axis'] |  | 3.9, 5.8 |
| create_drawing | PASS | sheets=[{'name': 'Sheet1', 'active': True}] size=[420.0, 297.0] first_angle=False scale=[1.0, 1.0] |  | 8.1 |
| create_drawing_sketch | PASS | sketch opened in 'Drawing View1', 1 segment drawn, closed |  | 8.10 |
| create_new_document | PASS | title=Part49 template=C:\ProgramData\SolidWorks\SOLIDWORKS 2017\templates\Part_Metric_MM.prtdot units=mm |  | 3.1, 4.1, 7.1, T3.1 |
| create_plane | PASS | planes 3->4 Block_Plane30 |  | 3.8, 5.7 |
| create_sketch | PASS | 4 lines, extents x 0..20 y 0..10, segments_added=4 |  | 3.5, 4.6, T3.3 |
| cut_extrude | PASS | volume=937.1681 expected=937.168 faces 6->7 |  | 3.5, T3.7 |
| delete_feature | PASS | pattern deleted; volume back to 46909.7788 |  | 3.11 |
| draft | PASS | volume=9481.4641; outward draft (inward 6681.8, outward 9481.5) |  | 5.4 |
| draw_3point_arc | PASS | 1 segment radius=10.0 |  | 4.2 |
| draw_arc | PASS | 1 segment radius=10.0 |  | 4.2 |
| draw_centerline | PASS | 1 construction line |  | 4.2, 5.1 |
| draw_circle | PASS | circle r=2 at (10,5) |  | 4.2, T3.6 |
| draw_ellipse | PASS | 1 ellipse |  | 4.2 |
| draw_line | PASS | 1 line [(0.0, 0.0), (30.0, 10.0)] |  | 4.2 |
| draw_point | PASS | sketch points 38 -> 39 |  | 4.2 |
| draw_polygon | PASS | 6 real + 1 construction segments |  | 4.2 |
| draw_rectangle | PASS | 4 lines, extents x 0..20 y 0..10, segments_added=4 |  | 4.2, T3.3 |
| draw_slot | PASS | 4 real + 1 construction segments |  | 4.2 |
| draw_spline | PASS | 1 spline |  | 4.2 |
| edit_sketch | PASS | reopened and closed Block_Sketch |  | 3.12 |
| export_document | FAIL/PASS | T3_core.step 31521 bytes header ok; overwrite refused: RuntimeError: Refusing to overwrite existing outpu | [9.3 export .3mf (dialog risk, run last)] export_document: SOLIDWORKS failed to export the document. (file on disk afterwards: True, 20001 bytes) | 2.10, 9.2, 9.3, T3.11 |
| fillet | PASS | volume=932.8761 expected=932.876 faces 7->11 |  | 3.4, T3.8 |
| get_active_document_info | PASS | title=Part49 template=C:\ProgramData\SolidWorks\SOLIDWORKS 2017\templates\Part_Metric_MM.prtdot units=mm |  | T3.1 |
| get_bounding_box | PASS | volume=1000.0 bodies=1 bbox=[20.0, 10.0, 5.0] |  | 2.2, 7.6, T3.5 |
| get_mass_properties | PASS | volume=932.8761 area=727.3982 (exp 727.40) com=[10.0, 5.0, 2.5] mass_g=0.932876 inertia_keys=False |  | T3.9 |
| get_sketch_status | PASS | status under_defined->under_defined; horizontal ok; dim SK_Len@SK_Draw@Part51.Part: 40 -> 25 |  | 4.4 |
| insert_center_marks | PASS | center-mark annotations 2 -> 3; legacy=0 |  | 8.13 |
| insert_centerlines | UNVERIFIED |  | handler ok (center_marks) on 'Drawing View3' but no annotation gained; the view may have no circular edges | 8.14 |
| insert_component | SILENT-FAIL/PASS | components=[('T3_core-1', [-10.0, -5.0, -2.5], True), ('T3_core-2', [90.0, -5.0, 17.5], False)] delta=[100.0, 0.0, 20.0] | [7.2c insert_component absolute origin] component inserted at (0,0,0) has origin [-10.0, -5.0, -2.5]; the x/y/z arguments do not place the component origin | 7.2, 7.2c |
| insert_detail_view | PASS | +1 detail view 'Detail View D (4 : 1)' scale=4.0 pos=[360.0, 250.0] |  | 8.9 |
| insert_model_annotations | PASS | handler dimensions_added=2; display dimensions 0 -> 2 |  | 8.11 |
| insert_model_view | PASS | +1 view 'Drawing View4' scale=0.5 GetDisplayMode=3 EdgesInShadedMode=True |  | 8.4 |
| insert_projected_view | PASS | +1 view Drawing View5 type=projected pos=[390.0, 60.0] |  | 8.5 |
| insert_section_view | PASS/UNVERIFIED | +1 section view 'Section View A-A' type=section scale=2.0 pos=[244.5, 110.69] (cut line at x=94.5, y 94.7..126.7) | section view created with depth_mm=3 ('Section View B-B'); whether depth was honoured (swCreateSectionView_Partial=16) cannot be measured through the API; ey... | 8.7, 8.8 |
| insert_standard_views | PASS | +3 views: [('Drawing View1', 'named', [94.5, 110.69]), ('Drawing View2', 'projected', [94.5, 229.49]), ('Drawing View3', 'projected', [241.5, 110.6... |  | 8.3 |
| linear_pattern | PASS | volume=46457.3895 expected=46457.389 |  | 3.7 |
| list_bodies | PASS | volume=1000.0 bodies=1 bbox=[20.0, 10.0, 5.0] |  | 2.2, 7.3, T3.5 |
| list_components | PASS | components=[('T3_core-1', [-10.0, -5.0, -2.5], True), ('T3_core-2', [90.0, -5.0, 17.5], False)] delta=[100.0, 0.0, 20.0] |  | 7.2 |
| list_dimensions | PASS | status under_defined->under_defined; horizontal ok; dim SK_Len@SK_Draw@Part51.Part: 40 -> 25 |  | 4.4 |
| list_drawing_views | PASS | +3 views: [('Drawing View1', 'named', [94.5, 110.69]), ('Drawing View2', 'projected', [94.5, 229.49]), ('Drawing View3', 'projected', [241.5, 110.6... |  | 8.16, 8.3 |
| list_edges | PASS | volume=932.8761 expected=932.876 faces 7->11 |  | 2.2, T3.8 |
| list_faces | PASS | F=11 E=26 V=16 Euler=1 cap_area=186.5752 cyl_faces=5 circle_edges=10 bbox=[20.0, 10.0, 5.0] |  | 2.2, 7.3 |
| list_features | PASS | 21 features: ['Comments', 'Favorites', 'History', 'Selection Sets', 'Sensors', 'Design Binder', 'Annotations', 'Surface Bodies', 'Solid Bodies', 'L... |  | 2.1 |
| list_mates | PASS | mates 0 -> 1 {'name': 'Coincident1', 'mate_type': 'coincident'}; origins after mate [('T3_core-2', [2.0, -5.0, -2.5]), ('T3_core-1', [-10.0, -5.0, ... |  | 7.4 |
| list_reference_planes | PASS | planes=['Front Plane', 'Top Plane', 'Right Plane'] axes=[] |  | 3.8, T3.2 |
| list_sheets | PASS | sheets=[{'name': 'Sheet1', 'active': True}] size=[420.0, 297.0] first_angle=False scale=[1.0, 1.0] |  | 8.1 |
| list_sketch_segments | PASS | 4 lines, extents x 0..20 y 0..10, segments_added=4 |  | T3.3 |
| list_sketches | PASS | sketches=['T3_Base'] open=False |  | T3.4 |
| list_vertices | PASS | F=11 E=26 V=16 Euler=1 cap_area=186.5752 cyl_faces=5 circle_edges=10 bbox=[20.0, 10.0, 5.0] |  | 2.2 |
| loft | PASS | volume=7000.0 expected=7000.0 |  | 5.7 |
| measure | PASS | face gap=5.0 edge=18.0 face_area=186.58 |  | 2.3 |
| mirror_feature | PASS | before 7874.34; after 7748.6726 (expected 7748.67) |  | 5.9 |
| open_document | PASS | reopened T3_core.sldprt; volume 932.8761 |  | 9.1 |
| rebuild_document | PASS | no problems; force_all rebuild ok; volume stable 932.8761 |  | 2.6 |
| rename_feature | PASS | Block_Boss -> Base_Block |  | 3.2 |
| revolve | PASS | volume=12566.3706 (quarter=12566.4); bbox z -21.21..21.21 (symmetric, +-21.21 expected); x 7.07..30.00 |  | 5.1, 5.2 |
| rib | FAIL/PASS | rib added 800.00 (expected 800) | [5.5 rib (default arguments)] rib: SOLIDWORKS did not create the rib. Check that the required selection was valid. Neither extrusion direction reac... | 5.5, 5.5b |
| save_active_document | PASS | dirty_before=True; mtime advanced; dirty_after=False; size=71829 |  | 2.9 |
| save_document | PASS | T3_core.sldprt 75866 bytes; overwrite refused: RuntimeError: Refusing to overwrite existing output: C:\_Pro |  | 7.6, 8.17, T3.10 |
| set_appearance | PASS | rgb readback (1.0, 0.0, 0.0) |  | 2.5 |
| set_component_fixed | PASS | fixed flags before={'T3_core-2': False, 'T3_core-1': True} after fix={'T3_core-2': True, 'T3_core-1': True} after float={'T3_core-2': False, 'T3_co... |  | 7.5 |
| set_construction_geometry | PASS | toggled on and off, read back both |  | 4.3 |
| set_dimension | PASS | status under_defined->under_defined; horizontal ok; dim SK_Len@SK_Draw@Part51.Part: 40 -> 25 |  | 4.4 |
| set_drawing_view | PASS | pos=(320.0,70.0) scale=0.4 mode=2 tangent=2 |  | 8.6 |
| set_feature_suppression | PASS | 46457.3895 -> 47242.7877 -> 46457.3895 |  | 3.10 |
| set_material | PASS | material=AISI 1020 density=7.9 mass_g=7.369721 |  | 2.4 |
| set_view | PASS | DisplayMode 3 -> 5 (5 = shaded with edges); 9 named views accepted |  | 2.7 |
| shell | PASS | volume=8072.0 expected=8072 |  | 5.3 |
| simple_hole | PASS | volume=46909.7788 expected=46909.779 |  | 3.6 |
| sketch_chamfer | PASS | segments 10 -> 11, chamfer line 7.071068 |  | 4.8 |
| sketch_fillet | PASS | segments 9 -> 10, arc r=5 |  | 4.7 |
| sketch_mirror | PASS | segments 12 -> 13; mirrored line x 290..270 |  | 4.10 |
| sketch_offset | PASS | segments 11 -> 12, radii at x=200: [10.0, 13.0] |  | 4.9 |
| sketch_trim | PASS | horizontal line endpoints after trim: [400.0, 420.0] |  | 4.11 |
| solidworks_status | PASS | revision=25.5.0 docs_open=0 output_root=C:\_Projects\solidworks-mcp\sandbox |  | 0.1 |
| sweep | PASS | volume=1130.9734 expected=1130.97 |  | 5.6 |
| demo_create_basketball, demo_upgrade_basketball | NOT-RUN | | opt-in tools, registered only with SW_MCP_DEMO_TOOLS; excluded from the 92 | |

## Case log

| Case | Status | Seconds | Evidence / note |
| --- | --- | --- | --- |
| 0.1 status | PASS | 0.04 | revision=25.5.0 docs_open=0 output_root=C:\_Projects\solidworks-mcp\sandbox |
| 0.2 negative: no document | PASS | 0.04 | RuntimeError: SOLIDWORKS has no active document. Create or o / RuntimeError: SOLIDWORKS has no active document. Create or o / RuntimeError: SOLIDWORKS has no active document. Create or o |
| T3.1 new part | PASS | 0.87 | title=Part49 template=C:\ProgramData\SolidWorks\SOLIDWORKS 2017\templates\Part_Metric_MM.prtdot units=mm |
| T3.2 reference planes | PASS | 1.78 | planes=['Front Plane', 'Top Plane', 'Right Plane'] axes=[] |
| T3.3 sketch rectangle | PASS | 4.09 | 4 lines, extents x 0..20 y 0..10, segments_added=4 |
| T3.4 close sketch | PASS | 2.12 | sketches=['T3_Base'] open=False |
| T3.5 boss extrude | PASS | 3.03 | volume=1000.0 bodies=1 bbox=[20.0, 10.0, 5.0] |
| T3.6 sketch circle | PASS | 5.9 | circle r=2 at (10,5) |
| T3.7 cut extrude | PASS | 5.01 | volume=937.1681 expected=937.168 faces 6->7 |
| T3.8 fillet | PASS | 22.93 | volume=932.8761 expected=932.876 faces 7->11 |
| T3.9 mass properties | PASS | 0.24 | volume=932.8761 area=727.3982 (exp 727.40) com=[10.0, 5.0, 2.5] mass_g=0.932876 inertia_keys=False |
| T3.10 save | PASS | 1.65 | T3_core.sldprt 75866 bytes; overwrite refused: RuntimeError: Refusing to overwrite existing output: C:\_Pro |
| T3.11 export STEP | PASS | 0.54 | T3_core.step 31521 bytes header ok; overwrite refused: RuntimeError: Refusing to overwrite existing outpu |
| 2.1 list_features | PASS | 1.26 | 21 features: ['Comments', 'Favorites', 'History', 'Selection Sets', 'Sensors', 'Design Binder', 'Annotations', 'Surface Bodies', 'Solid Bodies', 'Lights, Cameras and Scene', 'Equations', 'Material <not specified>', 'F... |
| 2.2 topology lists | PASS | 27.17 | F=11 E=26 V=16 Euler=1 cap_area=186.5752 cyl_faces=5 circle_edges=10 bbox=[20.0, 10.0, 5.0] |
| 2.3 measure | PASS | 14.36 | face gap=5.0 edge=18.0 face_area=186.58 |
| 2.4 set_material | PASS | 0.75 | material=AISI 1020 density=7.9 mass_g=7.369721 |
| 2.5 set_appearance | PASS | 0.31 | rgb readback (1.0, 0.0, 0.0) |
| 2.6 check_errors / rebuild | PASS | 1.67 | no problems; force_all rebuild ok; volume stable 932.8761 |
| 2.7 set_view + shaded-with-edges [verify-live #5] | PASS | 7.3 | DisplayMode 3 -> 5 (5 = shaded with edges); 9 named views accepted |
| 2.8 capture_screenshot | PASS | 2.61 | T3_screenshot.png 118824 bytes 800x496 stddev=88.7 |
| 2.9 save_active_document | PASS | 2.24 | dirty_before=True; mtime advanced; dirty_after=False; size=71829 |
| 2.10 export .x_t | PASS | 0.11 | T3_core.x_t 9412 bytes |
| 2.10 export .igs | PASS | 0.42 | T3_core.igs 72980 bytes |
| 2.10 export .png | PASS | 1.08 | T3_core.png 816931 bytes |
| 2.10 export .jpg | PASS | 0.76 | T3_core.jpg 268123 bytes |
| 3.1 new part + base boss | PASS | 5.2 | volume=48000.0 |
| 3.2 rename_feature | PASS | 2.24 | Block_Boss -> Base_Block |
| 3.3 chamfer | SILENT-FAIL | 9.91 | chamfer feature created but volume 48000.0 != 47960.0 (faces 6 -> 6); no geometry change |
| 3.3b chamfer angle_distance (workaround) | PASS | 10.14 | volume 48000.0 -> 47960.0 (expected 47960.0); faces +1 |
| 3.4 fillet | PASS | 11.39 | volume=47921.3717 expected=47921.372 |
| 3.5 sketch on face + cut blind | PASS | 5.36 | volume=47135.9735 expected=47135.974 |
| 3.6 simple_hole | PASS | 1.16 | volume=46909.7788 expected=46909.779 |
| 3.7 linear_pattern | PASS | 8.97 | volume=46457.3895 expected=46457.389 |
| 3.8 create_plane offset | PASS | 10.29 | planes 3->4 Block_Plane30 |
| 3.9 create_axis | PASS | 15.34 | axes 0->1: ['Block_Axis'] |
| 3.10 suppress / unsuppress | PASS | 4.5 | 46457.3895 -> 47242.7877 -> 46457.3895 |
| 3.11 delete_feature | PASS | 3.75 | pattern deleted; volume back to 46909.7788 |
| 3.12 edit_sketch | PASS | 5.54 | reopened and closed Block_Sketch |
| 3.13 convert_entities | PASS | 10.89 | segments 0 -> 8 |
| 4.1 sketch doc | PASS | 1.57 | sketch SK_Draw open |
| 4.2 draw_line | PASS | 3.87 | 1 line [(0.0, 0.0), (30.0, 10.0)] |
| 4.2 draw_centerline | PASS | 4.77 | 1 construction line |
| 4.2 draw_circle | PASS | 5.36 | 1 segment radius=5.0 |
| 4.2 draw_rectangle | PASS | 5.43 | 4 real + 0 construction segments |
| 4.2 draw_arc | PASS | 8.63 | 1 segment radius=10.0 |
| 4.2 draw_3point_arc | PASS | 7.6 | 1 segment radius=10.0 |
| 4.2 draw_ellipse | PASS | 9.17 | 1 ellipse |
| 4.2 draw_polygon | PASS | 10.55 | 6 real + 1 construction segments |
| 4.2 draw_slot | PASS | 14.65 | 4 real + 1 construction segments |
| 4.2 draw_spline | PASS | 16.54 | 1 spline |
| 4.2 draw_point | PASS | 3.46 | sketch points 38 -> 39 |
| 4.3 set_construction_geometry | PASS | 21.76 | toggled on and off, read back both |
| 4.4 dimension / relation / status | PASS | 20.33 | status under_defined->under_defined; horizontal ok; dim SK_Len@SK_Draw@Part51.Part: 40 -> 25 |
| 4.5 close SK_Draw | PASS | 1.9 | closed |
| 4.6 sketch edit sketch | PASS | 17.14 | 9 segments |
| 4.7 sketch_fillet | PASS | 9.94 | segments 9 -> 10, arc r=5 |
| 4.8 sketch_chamfer | PASS | 9.87 | segments 10 -> 11, chamfer line 7.071068 |
| 4.9 sketch_offset | PASS | 10.17 | segments 11 -> 12, radii at x=200: [10.0, 13.0] |
| 4.10 sketch_mirror | PASS | 12.11 | segments 12 -> 13; mirrored line x 290..270 |
| 4.11 sketch_trim | PASS | 11.69 | horizontal line endpoints after trim: [400.0, 420.0] |
| 4.12 close SK_Edit | PASS | 1.86 | closed |
| 5.1 revolve mid-plane [verify-live #1] | PASS | 4.71 | volume=12566.3706 (quarter=12566.4); bbox z -21.21..21.21 (symmetric, +-21.21 expected); x 7.07..30.00 |
| 5.2 revolve 360 + revolve cut | PASS | 8.46 | boss 50265.4825 (exp 50265.5); after cut 47438.0491 (exp 47438.0) |
| 5.3 shell | PASS | 7.63 | volume=8072.0 expected=8072 |
| 5.4 draft | PASS | 4.95 | volume=9481.4641; outward draft (inward 6681.8, outward 9481.5) |
| 5.5a rib bracket | PASS | 12.28 | bracket volume 15000.0; gusset line sketch ready |
| 5.5 rib (default arguments) | FAIL | 5.6 | rib: SOLIDWORKS did not create the rib. Check that the required selection was valid. Neither extrusion direction reached material: check that the profile spans between two existing faces. |
| 5.5b rib reverse_material=True | PASS | 5.05 | rib added 800.00 (expected 800) |
| 5.6 sweep | PASS | 3.43 | volume=1130.9734 expected=1130.97 |
| 5.7 loft + offset plane | PASS | 5.83 | volume=7000.0 expected=7000.0 |
| 5.8 circular_pattern | PASS | 11.66 | volume=27520.3516 expected=27520.35 |
| 5.9 mirror_feature | PASS | 6.41 | before 7874.34; after 7748.6726 (expected 7748.67) |
| 6.1 drawing model part | PASS | 11.47 | volume=7717.2567; dims=['Drw_W@Drw_Sketch@Part61.Part', 'Drw_H@Drw_Sketch@Part61.Part']; saved DRW.sldprt |
| 7.1 new assembly | PASS | 1.49 | title=Assem4 |
| 7.2 insert_component x2 (relative placement) | PASS | 0.96 | components=[('T3_core-1', [-10.0, -5.0, -2.5], True), ('T3_core-2', [90.0, -5.0, 17.5], False)] delta=[100.0, 0.0, 20.0] |
| 7.2c insert_component absolute origin | SILENT-FAIL | 0.0 | component inserted at (0,0,0) has origin [-10.0, -5.0, -2.5]; the x/y/z arguments do not place the component origin |
| 7.3 assembly topology | PASS | 1.46 | bodies=2 faces=22 (2 x 11) |
| 7.4 add_mate + list_mates | PASS | 9.54 | mates 0 -> 1 {'name': 'Coincident1', 'mate_type': 'coincident'}; origins after mate [('T3_core-2', [2.0, -5.0, -2.5]), ('T3_core-1', [-10.0, -5.0, -2.5])] |
| 7.5 set_component_fixed | PASS | 2.49 | fixed flags before={'T3_core-2': False, 'T3_core-1': True} after fix={'T3_core-2': True, 'T3_core-1': True} after float={'T3_core-2': False, 'T3_core-1': True} |
| 7.6 assembly bbox + save | PASS | 1.46 | bbox=[32.0, 10.0, 5.0] union_of_body_boxes=[32.0, 10.0, 5.0]; T3_asm.sldasm 66324 bytes |
| 8.1 create_drawing | PASS | 1.64 | sheets=[{'name': 'Sheet1', 'active': True}] size=[420.0, 297.0] first_angle=False scale=[1.0, 1.0] |
| 8.2 add_sheet / activate_sheet | PASS | 0.57 | sheets=['Sheet1', 'Sheet_Two'], reactivated Sheet1 |
| 8.3 insert_standard_views | PASS | 0.78 | +3 views: [('Drawing View1', 'named', [94.5, 110.69]), ('Drawing View2', 'projected', [94.5, 229.49]), ('Drawing View3', 'projected', [241.5, 110.69])] |
| 8.4 insert_model_view + shaded-with-edges [verify-live #2] | PASS | 1.5 | +1 view 'Drawing View4' scale=0.5 GetDisplayMode=3 EdgesInShadedMode=True |
| 8.5 insert_projected_view | PASS | 0.52 | +1 view Drawing View5 type=projected pos=[390.0, 60.0] |
| 8.6 set_drawing_view display/tangent [verify-live #2b] | PASS | 1.35 | pos=(320.0,70.0) scale=0.4 mode=2 tangent=2 |
| 8.7 insert_section_view [verify-live #3] | PASS | 2.69 | +1 section view 'Section View A-A' type=section scale=2.0 pos=[244.5, 110.69] (cut line at x=94.5, y 94.7..126.7) |
| 8.8 section with depth_mm (Partial question) [verify-live #3b] | UNVERIFIED | 2.79 | section view created with depth_mm=3 ('Section View B-B'); whether depth was honoured (swCreateSectionView_Partial=16) cannot be measured through the API; eyeball in the screenshot |
| 8.9 insert_detail_view [verify-live #4] | PASS | 1.19 | +1 detail view 'Detail View D (4 : 1)' scale=4.0 pos=[360.0, 250.0] |
| 8.10 activate_drawing_view / create_drawing_sketch | PASS | 0.26 | sketch opened in 'Drawing View1', 1 segment drawn, closed |
| 8.11 insert_model_annotations | PASS | 4.83 | handler dimensions_added=2; display dimensions 0 -> 2 |
| 8.12 auto_dimension_view | FAIL | 8.15 | auto_dimension_view: Auto-dimensioning added nothing (status 1). |
| 8.13 insert_center_marks | PASS | 5.58 | center-mark annotations 2 -> 3; legacy=0 |
| 8.14 insert_centerlines | UNVERIFIED | 11.63 | handler ok (center_marks) on 'Drawing View3' but no annotation gained; the view may have no circular edges |
| 8.15 add_note | PASS | 6.06 | note annotations (all views) 67 -> 68 |
| 8.16 final view list | PASS | 1.9 | 9 entries: [('Sheet1', 'sheet', 2.0), ('Drawing View1', 'named', 2.0), ('Drawing View2', 'projected', 2.0), ('Drawing View3', 'projected', 2.0), ('Drawing View4', 'named', 0.4), ('Drawing View5', 'projected', 0.4), ('... |
| 8.17 save drawing | PASS | 1.24 | DRW.slddrw 121044 bytes |
| 8.18 drawing screenshot | PASS | 1.08 | DRW_screenshot.png 56466 bytes |
| 9.1 open_document (sandbox file) | PASS | 3.7 | reopened T3_core.sldprt; volume 932.8761 |
| 9.2 export .stl (dialog risk, run last) | PASS | 0.09 | T3_core.stl 15284 bytes |
| 9.3 export .3mf (dialog risk, run last) | FAIL | 0.41 | export_document: SOLIDWORKS failed to export the document. (file on disk afterwards: True, 20001 bytes) |
| 99 cleanup own documents | PASS | 2.35 | closed 13 documents without saving; session back to baseline [] |

## Not exercised

- `demo_create_basketball`, `demo_upgrade_basketball`: opt-in (`SW_MCP_DEMO_TOOLS`), outside the 92.
- Not covered by an assertion: `list_mates` distance/angle values (only a coincident mate was added), `create_drawing` with `scale_numerator`/`first_angle=true`, `add_mate` types other than coincident, `insert_projected_view` with `not_aligned`, `selected_only` variants of centerlines/center marks, `insert_model_annotations` with source other than `entire_model`, `sketch_trim` modes other than `closest`.
- Documents the suite created were closed without saving at the end (`99 cleanup own documents`); the session returned to its baseline of no open documents. Files remain in the run folder.
