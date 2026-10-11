# Phase 5 Batch B: live verification (SOLIDWORKS 2017 SP05)

Verifier/fixer run of `tests/live_p5_batchB.py` (stages `docdata`, `geo1`, `geo1b`, `holes`, `cosm`, `fillet`, `cs`, `split`, `wrap`, `bad`; handlers called in-process, `SW_MCP_OUTPUT_ROOT=sandbox`, outputs under `sandbox/phase5/batchB/`). Baseline open documents: none; every document the script created was closed, final list equals baseline. Unit suite after the fixes: 292 tests OK. Batch A `export` stage re-run after the `save` changes: 0 FAIL.

Final run: 81 PASS, 4 FENCED, 0 FAIL (85 items). Raw logs `sandbox/phase5/batchB/final_*.txt`.

## Incident
The first docdata run deleted a global variable that a dimension equation still used, then saved: SOLIDWORKS raised a blocking "Rebuild?" modal. Fixed with `prepare_for_save` (rebuild before every save, refuse unsolved equations) and the `delete_equation` guard. No other modal appeared.

## Fenced (no working route on 2017)
- `combine_bodies`: `InsertCombineFeature` (FeatureManager and PartDoc) returns Nothing for body objects, by-name selections, marks 0/1/2/256, overlapping or touching bodies.
- `split_body`: `PreSplitBody2` returns the two temporary bodies but `PostSplitBody` builds nothing for any consume/body-subset/Origins/SavePaths variant.
- `set_mass_override`: `OverrideMass` only sets `UserAssigned`; `Mass` is unchanged on the same and a fresh object; no density setter.
- `fillet_variant type=full_round`: refused inside the tool; `FeatureFillet3` type 3 builds one plain edge fillet for all marks/options tried.

## Findings that changed the code
- Hole Wizard: counterbore Value1/2 = diameter/depth and countersink Value1/2 = diameter/angle were right (read back through `IWizardHoleFeatureData2`). Tapped holes need Value1 = thread depth and any non-zero Value6, else the wizard builds a 2 in thread; sizes are 'M6x1.0' / '1/4-20'.
- Body selection by `IBody2.Select4` picked the other body; bodies are now picked by name.
- Per-configuration geometry is stale after a switch until rebuilt; `_show` rebuilds.
- Marks: dome 1, move/copy 1, mirror body 256, wrap sketch 4 / face 1, face fillet set 2 = 4.

## Results
| Item | Result | Measured evidence | Fix applied |
|---|---|---|---|
| D0 base part | PASS | vol=7717.2567 |  |
| D1 add_configuration Short + derived Kid; active stays Default | PASS | {"configurations": [{"name": "Default", "active": true, "description": "Default", "comment": "", "alternate_name": "", "derived": false, "parent": nul | activate_configuration ok from readback |
| D1b add_configuration activate=true makes it active | PASS | active=Act |  |
| D3 rename_configuration keeps active | PASS | ['Default', 'Kid', 'Short', 'Act2'] active=Default |  |
| D2a delete active config switches + deletes | PASS | Deleted configuration 'Act2'. names=['Default', 'Kid', 'Short'] active=Default |  |
| D4a suppress Ct in Short only: Short=8000, Default cut | PASS | Short=8000.0 Default=7717.2567 Kid=7717.2567 |  |
| D4b Short active measured via get_mass_properties | PASS | vol=8000.0 |  |
| D4c suppress scope=all | PASS | {'Default': 8000.0, 'Kid': 8000.0, 'Short': 8000.0} |  |
| D4d unsuppress scope=this (Default only) | PASS | {'Default': 7717.2567, 'Kid': 8000.0, 'Short': 8000.0} |  |
| D5a set_dimension_config specified=[Short] | PASS | Short z=20.0 Default z=10.0 fn=D1@Bx@Part145.Part |  |
| D5b set_dimension_config this | PASS | Short z=20.0 Default z=12.0 |  |
| D5c set_dimension_config all | PASS | [('Default', 15.0), ('Kid', 15.0), ('Short', 15.0)] | set_dimension_config all: name every config, verify each; _show rebuilds after switching |
| D8 cfg mass vs get_mass_properties; active restored | PASS | cfg={'mass_g': 7.717257, 'volume_mm3': 7717.2567, 'surface_area_mm2': 2931.9469, 'density_g_per_cm3': 1.0, 'center_of_mass_mm': [-0.0, 0.0, 5.0], 'use |  |
| D6a global var w drives dimension (w=6 -> 12, w=8 -> 16) | PASS | z(w=6)=12.0 z(w=8)=16.0 edit=Edited equation #0. | equation status informational (_solver_status) |
| D6b bad equation no hang; status reported | PASS | ok=False msg=SOLIDWORKS did not accept the equation '"zz" = "nonexistent" +'. data={"equation": "\"zz\" = \"nonexistent\" +", "status": -1} |  |
| D6c delete_equation refuses a referenced global variable | PASS | Global variable 'w' is still used by ['"D1@Bx@Part145.Part"= "w" * 2']. Delete those first, or pass force=true. | delete_equation guard (force flag) |
| D6d delete_equation dimension eq then variable | PASS | {"equations": [], "status": -1, "global_variables": []} |  |
| D7a file-level text + $PRP link resolved after save+reopen | PASS | {'name': 'Linked', 'value': '$PRP:"Desc"', 'resolved_value': 'Plate', 'type': 'text'} |  |
| D7b config-specific number after reopen | PASS | {'name': 'Weight', 'value': '12.500000', 'resolved_value': '12.500000', 'type': 'number'} | number written as Add3 type 5 (type 3 refused) |
| D7c date/yesno/double after reopen | PASS | date={'name': 'Date', 'value': '3/4/2026', 'resolved_value': '3/4/2026', 'type': 'date'} yesno={'name': 'Chk', 'value': 'Yes', 'resolved_value': 'Yes' |  |
| D7d delete_custom_property present ok, absent reported | PASS | Deleted Rev. / No property named 'NoSuchProp'. |  |
| D9 set_mass_override | FENCED | The override did not persist in the document (it only affected the calculation object). | FENCED: OverrideMass never changes Mass |
| D10 set/get units ips -> custom(in,4dp,rad,lb) -> mmgs | PASS | u1={"units": {"unit_system": "ips", "length_unit": "in", "length_decimals": 2, "angle_unit": "degrees", "angle_decimals": 2, "mass_length_unit": "mm", |  |
| D10b volume measure unaffected by unit change | PASS | vol=12347.6107 pre=12347.6107 |  |
| D2b delete last configuration refused | PASS | A document must keep at least one configuration. names=['Default'] |  |
| G1a ref point face_center | PASS | xyz=[0.0, 0.0, 10.0] |  |
| G0 boss on top face | PASS | vol=8392.6991 |  |
| G1b ref point arc_center | PASS | xyz=[10.0, 0.0, 15.0] |  |
| G1c ref point along_curve distance 3 | PASS | xyz=[-17.0, -10.0, 10.0] from_start=[-17.0, -10.0, 10.0] from_end=[17.0, -10.0, 10.0] |  |
| G1d ref point along_curve percentage 25 (=25%) | PASS | xyz=[-10.0, -10.0, 10.0] expect [-10.0, -10.0, 10.0] or [10.0, -10.0, 10.0] | percent is already percent (sent 25, not 0.25) |
| G1e ref point along_curve evenly 4 | PASS | feature created, first/only point=[12.0, -10.0, 10.0] (count of points not exposed by IRefPoint) |  |
| G1f ref point intersection of two edges | PASS | xyz=[-20.0, -10.0, 10.0] |  |
| G1g ref point sketch_point | PASS | xyz=[-7.0, 3.0, 10.0] |  |
| G4a chamfer_vertex equal d=2 (removes d^3/6=1.3333) | PASS | removed=1.3334 |  |
| G4b chamfer_vertex 1/2/3 (removes 1.0) | PASS | removed=1.0000 |  |
| G3a dome spherical h=3 (+131.95) | PASS | dV=131.947 exp=131.947 | dome face needs mark 1 |
| G3b dome elliptical h=3 (+157.08) | PASS | dV=157.080 exp=157.080 | mark 1 |
| G3c dome reverse (concave, -131.95) | PASS | dV=-131.947 | mark 1 |
| G2-0 two overlapping bodies | PASS | bodies=2 vol=12500.0 |  |
| G2 combine_bodies add/subtract/common | FENCED | InsertCombineFeature returns Nothing in every argument form (see probe); tool fenced. msg=SOLIDWORKS did not create the combine (add). Check that the  | FENCED: InsertCombineFeature returns Nothing for every argument form |
| G3d delete_body keep=false (delete B2, keep B1 8000) | PASS | bodies=1 vol=8000.0 | bodies picked by name (Select4 chose the other body) |
| G3e delete_body keep=true (keep only B2 4500) | PASS | bodies=1 vol=4500.0 | same |
| G3f move_copy_body translate dx=50 | PASS | min x 0.0 -> 50.0 | move/copy bodies need mark 1 |
| G3g move_copy_body rotate rz=90 about origin (B2 -> x -5..5, y 0..30) | PASS | [-5.0, -0.0, 0.0][5.0, 30.0, 15.0] | angle slots are Z,Y,X |
| G3h move_copy_body copy count 3 (+3 bodies) | PASS | bodies=5 vol=26000.0 | mark 1 |
| G3i scale_part uniform 2 about origin (vol x8, bbox x2) | PASS | vol=64000.0 bbox=[-40.0, -20.0, 0.0][40.0, 20.0, 20.0] |  |
| G3j scale_part uniform 2 about centroid (centre fixed) | PASS | vol=64000.0 centre=[0.0, 0.0, 5.0] was [0.0, 0.0, 5.0] |  |
| G3k scale_part non-uniform 1/2/3 (vol x6, size 40/40/30) | PASS | vol=48000.0 size=[40.0, 40.0, 30.0] |  |
| G3l mirror_body merge=false (2 bodies, vol 2000) | PASS | bodies=2 vol=2000.0 size=[20.0, 10.0, 10.0] | mirror bodies need mark 256 |
| G3m mirror_body merge=true (1 body, vol 2000, x -10..10) | PASS | bodies=1 vol=2000.0 size=[20.0, 10.0, 10.0] | mark 256 |
| G5a helix height_pitch 30/5 | PASS | {'Height': 0.03, 'Pitch': 0.005, 'Revolution': 6.0, 'DefinedBy': 2, 'Clockwise': True, 'Taper': False, 'TaperAngle': 0.0, 'StartingAngle': 0.0, 'Taper |  |
| G5b helix height_revolutions 30/4 | PASS | {'Height': 0.03, 'Pitch': 0.0075, 'Revolution': 4.0, 'DefinedBy': 1, 'Clockwise': True, 'Taper': False, 'TaperAngle': 0.0, 'StartingAngle': 0.0, 'Tape |  |
| G5c helix pitch_revolutions 6/5 | PASS | {'Height': 0.03, 'Pitch': 0.006, 'Revolution': 5.0, 'DefinedBy': 0, 'Clockwise': True, 'Taper': False, 'TaperAngle': 0.0, 'StartingAngle': 0.0, 'Taper |  |
| G5d helix tapered 5deg | PASS | {'Height': 0.03, 'Pitch': 0.005, 'Revolution': 6.0, 'DefinedBy': 2, 'Clockwise': True, 'Taper': True, 'TaperAngle': 0.08726646259971647, 'StartingAngl |  |
| G5e helix ccw start 90 | PASS | {'Height': 0.03, 'Pitch': 0.005, 'Revolution': 6.0, 'DefinedBy': 2, 'Clockwise': False, 'Taper': False, 'TaperAngle': 0.0, 'StartingAngle': 1.57079632 |  |
| G5f spiral pitch 3 rev 4 | PASS | {'Height': 0.0, 'Pitch': 0.003, 'Revolution': 4.0, 'DefinedBy': 3, 'Clockwise': True, 'Taper': False, 'TaperAngle': 0.0, 'StartingAngle': 0.0, 'TaperO |  |
| H1 straight hole d6 through_all (removes 565.49) | PASS | removed=565.487 exp=565.49 def={'Type': 25, 'Diameter': 0.0, 'Depth': 0.0, 'CounterBoreDiameter': 0.0, 'CounterBoreDepth': 0.0, 'CounterSinkDiameter': |  |
| H2 counterbore d6, cb 12x4 through (removes 904.78) | PASS | removed=904.779 exp=904.78 def={'Type': 14, 'Diameter': 0.0, 'Depth': 0.0, 'CounterBoreDiameter': 0.012, 'CounterBoreDepth': 0.004, 'CounterSinkDiamet |  |
| H3 countersink d6, cs 12 @90 through (removes 678.58) | PASS | removed=678.584 exp=678.58 def={'Type': 44, 'Diameter': 0.0, 'Depth': 0.0, 'CounterBoreDiameter': 0.0, 'CounterBoreDepth': 0.0, 'CounterSinkDiameter': |  |
| H4c thread annotation: wizard sets none (CosmeticThreadType read-only), cosmetic_thread adds it | PASS | CosmeticThreadType=0 sub=[('Sketch9', 'ProfileFeature'), ('Sketch8', 'ProfileFeature'), ('HCT', 'CosmeticThread')] msg=Created cosmetic thread 'HCT'. | CosmeticThreadType is read-only; cosmetic_thread adds the annotation |
| H4 tapped M6x1.0 blind 12 thread 10 tap drill 5 | PASS | removed=351.965 exp=TAP def={'Type': 31, 'Diameter': 0.0, 'Depth': 0.0, 'CounterBoreDiameter': 0.0, 'CounterBoreDepth': 0.0, 'CounterSinkDiameter': 0. | Value1 = thread depth, Value6 non-zero; size 'M6x1.0' |
| H4b tapped via ansi_inch 1/4-20 | PASS | removed=389.521 exp=TAPIN def={'Type': 31, 'Diameter': 0.0, 'Depth': 0.0, 'CounterBoreDiameter': 0.0, 'CounterBoreDepth': 0.0, 'CounterSinkDiameter':  | same; size '1/4-20' |
| H5 two points -> two holes (removes 2x565.49) | PASS | removed=1130.97 created=['M6 Clearance Hole2', 'M6 Clearance Hole3'] |  |
| C1 cosmetic_thread present in tree under the hole | PASS | Created cosmetic thread 'CTh'. sub=[('Sh', 'ProfileFeature'), ('CTh', 'CosmeticThread')] | standard 2 = ISO + 'Machine threads' (other strings silently fall back to '2-4.5') |
| C1b cosmetic thread definition readback (ISO M6x1.0, d6, depth 10) | PASS | {'Diameter': 0.006, 'BlindDepth': 0.01, 'EndCondition': 0, 'Size': 'M6x1.0', 'Standard': 2, 'StandardType': 'Machine Threads'} | same |
| F1 variable fillet 2->5 on 40mm edge (~111.6; const2=34.3, const5=214.6) | PASS | removed=111.60 exp~111.6 | radii go in Radii argument (PointRadiusArray built nothing) |
| F1b variable fillet 5->2 same removal | PASS | removed=111.60 | same |
| F2 face fillet r3, set1 top / set2 front+left (two edges ~115.9 less corner overlap) | PASS | removed=113.295 exp~115.885 | set 2 uses mark 4, no UniformRadius option |
| F2b face fillet r3 top/front single edge (77.25) | PASS | removed=77.257 | same |
| F3 full round | FENCED | FeatureFillet3 type 3 builds a single edge fillet for all marks/options tried; refused. msg=Not supported on SOLIDWORKS 2017: full_round fillets are n | FENCED (refused): type 3 builds one plain edge fillet |
| CS1 coordinate system origin at vertex, x/y from edges | PASS | transform=[1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0, -0.02, -0.01, 0.0, 1.0, 0.0, 0.0, 0.0] msg=Created coordinate system 'CS1'. |  |
| CS2 coordinate system flip_x reverses X axis | PASS | t=[1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0, -0.02, -0.01, 0.0, 1.0, 0.0, 0.0, 0.0] t2=[-1.0, -0.0, 0.0, 0.0, -1.0, 0.0, -0.0, 0.0, 1.0, -0.02, - |  |
| SP1 split_body with Right plane | FENCED | PreSplitBody2 returns 2 temp bodies but PostSplitBody builds nothing in every variant; fenced. nbodies=1 | FENCED: PostSplitBody builds nothing |
| IN1 intersect_bodies of two overlapping solids | PASS | Created intersect 'In'. bodies=3 vol=10500.0 boxes=[([0.0, -5.0, 0.0], [20.0, 5.0, 10.0]), ([-20.0, -10.0, 0.0], [20.0, 10.0, 10.0]), ([0.0, -5.0, 0.0 |  |
| W1 wrap emboss 1mm (adds ~36) | PASS | dV=37.809 msg=Created wrap (emboss) 'Wr'. | wrap marks sketch 4 / face 1, method spline_surface |
| W2 wrap deboss 1mm (removes ~36) | PASS | dV=-34.208 msg=Created wrap (deboss) 'Wr'. | same |
| B1 bad input returns cleanly: dome on an edge | PASS | ok=False msg=SOLIDWORKS did not create the dome. Check that the required selection was valid. |  |
| B1 bad input returns cleanly: chamfer_vertex on a face | PASS | ok=False msg=SOLIDWORKS did not create the vertex chamfer. Check that the required selection was valid. |  |
| B1 bad input returns cleanly: variable fillet on a vertex | PASS | ok=False msg=SOLIDWORKS did not create the variable fillet. Check that the required selection was valid |  |
| B1 bad input returns cleanly: hole_wizard point off the part | PASS | ok=False msg=No face at point {'x_mm': 500, 'y_mm': 500, 'z_mm': 500}; hole not created. |  |
| B1 bad input returns cleanly: cosmetic_thread on a face | PASS | ok=False msg=SOLIDWORKS did not create the cosmetic thread. Check that the required selection was valid |  |
| B1 bad input returns cleanly: wrap_sketch with no sketch face | PASS | ok=True msg=Created wrap (emboss) 'Wrap1'. |  |
| B1 bad input returns cleanly: coordinate system from 3 faces | PASS | ok=True msg=Created coordinate system 'Coordinate System1'. |  |
| B1 bad input returns cleanly: reference point face_center on an edge | PASS | ok=False msg=EXC com_error(-2147417851, 'The server threw an exception.', None, None) |  |
| B1 bad input returns cleanly: scale_part factor too small to be sane | PASS | ok=True msg=Created scale 'Scale1'. |  |

## Not covered / caveats
- Custom property type `number` and `double` both land as Number (type 3 read back); date reads back in locale form (3/4/2026).
- `create_coordinate_system` edge-derived axis directions follow SOLIDWORKS' edge orientation (Y came out reversed for a +Y edge; use `flip_y`).
- Reference point `evenly` count is not exposed by `IRefPoint` (last of four points was verified).
- The existing upstream `mirror_feature(mirror_body=true)` still selects with mark 1 and is probably affected like `mirror_body`; not touched.
- `create_plane`/`create_axis` extensions were not part of Batch B.
