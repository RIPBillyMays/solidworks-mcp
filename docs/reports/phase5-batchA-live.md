# Phase 5 Batch A: live verification (SOLIDWORKS 2017 SP05)

Verifier/fixer run of `tests/live_p5_batchA.py` (stages `feature`, `export`, `asm`, `asm2`, `extra`; tool handlers called in-process, `SW_MCP_OUTPUT_ROOT=sandbox`, outputs under `sandbox/phase5/batchA/`). Baseline open documents: none; every document the script created was closed; final document list equals baseline. Full unit suite after the fixes: 227 tests, OK.

Result: 189 PASS, 1 FENCED (`redo`), 0 FAIL on the final run. Each FAIL seen during development was diagnosed and fixed (see "Defects found"). Raw log: `sandbox/phase5/batchA/live_log.txt`.

## Unverified-from-memory items, now settled
- STEP AP: `swStepAP` 203 writes `FILE_SCHEMA ('CONFIG_CONTROL_DESIGN')`, 214 writes `('AUTOMOTIVE_DESIGN')` (part and assembly). Encoding in `STEP_VERSIONS` is correct.
- STL: default is binary (`84 + 50 x triangles` bytes confirmed), `stl_format=ascii` starts `solid`. Deviation/angle are metres/radians (custom 0.005 mm / 5 deg gave 548 triangles vs 156 coarse, 236 fine). `units` mm/cm/m/in scale the file bbox 1 / 0.1 / 0.001 / 1/25.4. `translate_to_positive` verified by bbox min.
- VRML: `swExportVrmlVersion` 1 writes `#VRML V2.0 utf8`, 2 writes `#VRML V1.0 ascii` (the planned alias `2001` was wrong, replaced by `01`); `swExportVrmlUnits` verified by coordinates (mm, in, default m).
- Second-direction end target: mark 2 is right (`target2` up_to_surface gave the exact volume).
- Thin features: the assumed encoding was wrong (no separate thin-type argument; see defects). Mid-plane now: wall centred, Thk1 = total.
- `EditMate4` argument order is correct (16 args incl. `RepairMatesWithSameMissingEntity`) but the call is a no-op on 2017, so `edit_mate` re-creates the mate.
- `ReplaceComponents2` order (file, config, replace-all, use-config-choice, re-attach mates) is correct: mate preserved, no modal dialog.
- Preferences: all user preferences touched by exports read back identical after each call (STL deviation/angle values scale with the active model, so doubles are compared in the same document).

## Defects found and fixed
1. Thin extrude/cut/revolve: `RevThinDir` is the `swThinWallType_e` (two-direction and mid-plane were ignored); revolve with `IsSolid=False` built a surface.
2. `up_to_body` / `body_name` targets: `IBody2.Select4` refuses; fall back to `SelectByID2(name, "SOLIDBODY")`.
3. `undo` reported failure (EditUndo2 returns void); `redo` does nothing (EditRedo/EditRedo2, immediate or delayed) so it is FENCED (`sw2017_fences.py`). One feature can take several undo steps.
4. BMP export: `Extension.SaveAs` error 256; now `IModelDoc2.SaveBMP`.
5. STL quality restore: quality 3 (custom) cannot be set directly, and presets rewrite deviation/angle, so exports left the user on "coarse". Restored as a group. VRML version 0 is not accepted back; restored as 2 (same output).
6. `export_bodies`: `IBody2.Save` takes an IStream. Rewritten as select body + `SaveAs` (x_t, x_b, step, sat, iges, stl; 3mf ignores the selection and is refused).
7. `export_components`: STL from a part inside an active assembly exported the whole assembly (activate each part first); lightweight components report `IsSuppressed` true and were skipped, now resolved and exported.
8. `edit_mate`: missing `RepairMatesWithSameMissingEntity` argument; EditMate4 is a no-op, so flip/alignment/limits re-create the mate (original restored on refusal; name preserved).
9. Width mate: AddMate5 needs the tab faces at mark 16 (width faces mark 1); `add_mate` maps mark 2 to 16.
10. `insert_component` with `configuration`: option 2 is `NewConfigWithAsmStructure` and fails; use option 0 and set `ReferencedConfiguration` if needed.
11. `list_mates.dimension_name` was bare `D1`; now `D1@<mate>` (accepted by `set_dimension`).

## Not reproducible or caveats
- Dialog guard (F12): toggles 10 and 77 read off inside `dialogs_suppressed()`, restored after; an erroring feature (bow-tie sketch) returned a clean failure with "show errors every rebuild" ON and no dialog.
- `create_subassembly` was not implemented by the batch (not tested).
- 3D PDF carries `/PRC` (not `/U3D`).
- Inserting without `configuration` uses the part's active configuration (follows whichever configuration was opened last).
- `ActivateDoc3` re-activation is relied on by `export_components`; if an export fails midway the assembly is re-activated in `finally`.

## Results
| Item | Result | Measured evidence | Fix applied |
|---|---|---|---|
| F1a boss blind 10 | PASS | vol=8000.0 |  |
| F1b cut through_all | PASS | vol=7717.2567 exp=7717.26 |  |
| F1c revolve 360 | PASS | vol=6283.1853 exp=6283.19 |  |
| F11a revolve angle+angle2 (90+90=half) | PASS | vol=3141.5927 exp=3141.59 |  |
| F11b revolve mid_plane 180 | PASS | vol=3141.5927 bbox=[-20.0, -10.0, -10.0][20.0, 20.0, 10.0] |  |
| F11c one_direction revolve thin (open profile) | PASS | vol=691.1504 exp=None (1-dir: 691.2 out or 565.5 in) msg=Created revolve 'RvT'. | Thin features: thin type travels in RevThinDir (swThinWallType_e), Thk1 is the total for mid-plane; revolve IsSolid stays True (False built a surface) |
| F11d mid_plane revolve thin (open profile) | PASS | vol=1256.6371 exp=1256.6370614359173 (1-dir: 691.2 out or 565.5 in) msg=Created revolve 'RvT'. | Thin features: thin type travels in RevThinDir (swThinWallType_e), Thk1 is the total for mid-plane; revolve IsSolid stays True (False built a surface) |
| F11e two_directions revolve thin (open profile) | PASS | vol=1256.6371 exp=1256.6370614359173 (1-dir: 691.2 out or 565.5 in) msg=Created revolve 'RvT'. | Thin features: thin type travels in RevThinDir (swThinWallType_e), Thk1 is the total for mid-plane; revolve IsSolid stays True (False built a surface) |
| F8 draft in < 8000 < out | PASS | in=7485.2737 out=8535.1377 |  |
| F7a second direction 10+5 | PASS | bbox z -5.0..10.0 vol=12000.0 |  |
| F7b second direction + draft2 | PASS | vol=11870.0427 (undrafted 12000) |  |
| F-mid boss mid_plane | PASS | z -5.0..5.0 |  |
| F9 thin one_direction | PASS | vol=2560.0 exp=2560 bbox=[-22.0, -12.0, 0.0][22.0, 25.0, 10.0] msg=Created boss extrusion 'Th'. | Thin features: thin type travels in RevThinDir (swThinWallType_e), Thk1 is the total for mid-plane; revolve IsSolid stays True (False built a surface) |
| F9 thin two_directions | PASS | vol=3720.0 exp=3720 bbox=[-22.0, -12.0, 0.0][22.0, 25.0, 10.0] msg=Created boss extrusion 'Th'. | Thin features: thin type travels in RevThinDir (swThinWallType_e), Thk1 is the total for mid-plane; revolve IsSolid stays True (False built a surface) |
| F9 thin mid_plane | PASS | vol=2400.0 exp=2400 bbox=[-21.0, -11.0, 0.0][21.0, 25.0, 10.0] msg=Created boss extrusion 'Th'. | Thin features: thin type travels in RevThinDir (swThinWallType_e), Thk1 is the total for mid-plane; revolve IsSolid stays True (False built a surface) |
| F9 thin cap_ends | PASS | vol=4160.0 msg=Created boss extrusion 'Th'. | Thin features: thin type travels in RevThinDir (swThinWallType_e), Thk1 is the total for mid-plane; revolve IsSolid stays True (False built a surface) |
| F10a cut flip_side (remove outside profile) | PASS | normal=6000.0 flip=2000.0 |  |
| F10b thin cut | PASS | vol=7360.0 msg=Created cut 'CutT'. The requested direction removed nothing, so it was cut the other way. | Thin features: thin type travels in RevThinDir (swThinWallType_e), Thk1 is the total for mid-plane; revolve IsSolid stays True (False built a surface) |
| F-slab | PASS | vol=64000.0 |  |
| F2 up_to_surface | PASS | dvol=3926.99 exp=3926.99 Created boss extrusion 'UTS'. |  |
| F4a offset_from_surface 2 | PASS | dvol=3769.91 -> length=48.00 (48 or 52) |  |
| F4b offset_from_surface 2 reversed | PASS | dvol=4084.07 -> length=52.00 |  |
| F3a up_to_vertex | PASS | dvol=3926.99 exp=3926.99 Created boss extrusion 'UTV'. |  |
| F3b up_to_body (index) | PASS | dvol=3926.99 exp=3926.99 Created boss extrusion 'UTB'. | Body targets: IBody2.Select4 refuses on 2017; fall back to SelectByID2(name,'SOLIDBODY') |
| F6a target body_name | PASS | dvol=3926.99 Created boss extrusion 'UTB2'. | Body targets: IBody2.Select4 refuses on 2017; fall back to SelectByID2(name,'SOLIDBODY') |
| F6b target feature+face_index | PASS | dvol=3926.99 Created boss extrusion 'UTF'. |  |
| F6c target point | PASS | dvol=3926.99 Created boss extrusion 'UTP'. |  |
| F5 second-direction end target (mark) | PASS | dvol=2356.19 exp=2356.19 Created boss extrusion 'D2'. |  |
| F5b dir1 up_to_surface + dir2 blind | PASS | dvol=2356.19 exp=2356.19 Created boss extrusion 'D1'. |  |
| F13a undo removes the feature | PASS | feat 31->32 undo->31; vol 64235.6194 -> 64000.0; Undid 1 step(s); feature count 32 -> 31. | undo: EditUndo2 returns void, so ok is judged by the feature tree; redo fenced (EditRedo/EditRedo2 do nothing) |
| F13b redo | FENCED | EditRedo2/EditRedo no-ops (feat 31->31, volume unchanged) | undo: EditUndo2 returns void, so ok is judged by the feature tree; redo fenced (EditRedo/EditRedo2 do nothing) |
| F14a select by name | PASS | Selected PLANE; 1 object(s) now selected. |  |
| F14b select by point | PASS | Selected FACE; 1 object(s) now selected. |  |
| F14c select by ray | PASS | Selected FACE; 1 object(s) now selected. |  |
| F14d clear_selection | PASS | Selection cleared. {'selected_count': 0} |  |
| F12 dialog toggles readable after features | PASS | toggle10=True toggle77=True |  |
| final docs == baseline | PASS | [] vs [] |  |
| E0 list_export_formats | PASS | 19 formats; unsupported=['.obj', 'AP242'] |  |
| E1 STEP AP203 header | PASS | FILE_SCHEMA  'CONFIG_CONTROL_DESIGN'  applied=[(75, 203)] |  |
| E1 STEP AP214 header | PASS | FILE_SCHEMA  'AUTOMOTIVE_DESIGN'  applied=[(75, 214)] |  |
| E1c STEP default (no option) | PASS | schema  'CONFIG_CONTROL_DESIGN'  |  |
| E5 prefs restored after STEP | PASS | {'step_ap': 203, 'stl_quality': 3, 'stl_units': 0, 'vrml_units': 2, 'vrml_ver': 2, 'stl_dev': 3.542186963589056e-06, 'stl_ang': 0.174532925199433, 'stl_bin': True, 'stl_nt': False, 'stl_one': False, 'vrml_one': True} | STL quality/deviation/angle restored as a group (custom quality cannot be set directly); VRML version 0 restores as 2; readback verified |
| E3a STL ascii flag | PASS | 182113 |  |
| E3b STL binary flag + size=84+50n | PASS | {'binary': True, 'tri': 644, 'min': [0.0, 0.0, 0.0], 'max': [55.0, 20.0, 20.0], 'bytes': 32284} |  |
| E3c STL default format | PASS | default binary=True |  |
| E2 STL quality ordering coarse<fine<custom_tiny | PASS | coarse=156 fine=236 custom_tiny=548 | STL quality/deviation/angle restored as a group (custom quality cannot be set directly); VRML version 0 restores as 2; readback verified |
| E3d STL units mm (bbox 55x20x20) | PASS | [55.0, 20.0, 20.0] |  |
| E3e STL units in (bbox/25.4) | PASS | [2.165, 0.787, 0.787] |  |
| E4a STL units cm | PASS | [5.5, 2.0, 2.0] |  |
| E4b STL units m | PASS | [0.055, 0.02, 0.02] |  |
| E3f STL translate_to_positive | PASS | translate min=[0.0, 0.0, 0.0] no-translate min=[-30.0, -10.0, 0.0] |  |
| E5b prefs restored after STL | PASS | {'step_ap': 203, 'stl_quality': 3, 'stl_units': 0, 'vrml_units': 2, 'vrml_ver': 2, 'stl_dev': 3.542186963589056e-06, 'stl_ang': 0.174532925199433, 'stl_bin': True, 'stl_nt': False, 'stl_one': False, 'vrml_one': True} vs {'step_ap' | STL quality/deviation/angle restored as a group (custom quality cannot be set directly); VRML version 0 restores as 2; readback verified |
| E4 VRML w_default.wrl | PASS | hdr=b'#VRML V1.0 ascii\r' applied=[] Exported document to C:\_Projects\solidworks-mcp\sandbox\pha |  |
| E4 VRML w_in.wrl | PASS | hdr=b'#VRML V1.0 ascii\r' applied=[(212, 3)] Exported document to C:\_Projects\solidworks-mcp\sandbox\pha |  |
| E4 VRML w_mm.wrl | PASS | hdr=b'#VRML V1.0 ascii\r' applied=[(212, 0)] Exported document to C:\_Projects\solidworks-mcp\sandbox\pha |  |
| E4 VRML w_v97.wrl | PASS | hdr=b'#VRML V2.0 utf8\r' applied=[(384, 1)] Exported document to C:\_Projects\solidworks-mcp\sandbox\pha | VRML version aliases corrected ('01' = VRML 1.0, '97' = VRML 2.0; '2001' removed) |
| E4 VRML w_v01.wrl | PASS | hdr=b'#VRML V1.0 ascii\r' applied=[(384, 2)] Exported document to C:\_Projects\solidworks-mcp\sandbox\pha | VRML version aliases corrected ('01' = VRML 1.0, '97' = VRML 2.0; '2001' removed) |
| E4 VRML w_one.wrl | PASS | hdr=b'#VRML V1.0 ascii\r' applied=[(246, True)] Exported document to C:\_Projects\solidworks-mcp\sandbox\pha |  |
| E4c VRML units measured in coordinates (part spans x -30..25 mm) | PASS | mm=(-30.0, 25.0) in=(-1.181102, 0.984252) default(m)=(-0.03, 0.025) |  |
| E5c prefs restored after VRML | PASS | {'step_ap': 203, 'stl_quality': 3, 'stl_units': 0, 'vrml_units': 2, 'vrml_ver': 2, 'stl_dev': 3.542186963589056e-06, 'stl_ang': 0.174532925199433, 'stl_bin': True, 'stl_nt': False, 'stl_one': False, 'vrml_one': True} | STL quality/deviation/angle restored as a group (custom quality cannot be set directly); VRML version 0 restores as 2; readback verified |
| E7 p.sat | PASS | bytes=9820 hdr=b'2200 0 2 0           \r\n1' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\p. |  |
| E7 p.x_t | PASS | bytes=7608 hdr=b'**ABCDEFGHIJKLMNOPQRSTUV' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\p. |  |
| E7 p.x_b | PASS | bytes=7470 hdr=b'**ABCDEFGHIJKLMNOPQRSTUV' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\p. |  |
| E7 p.igs | PASS | bytes=43050 hdr=b'SolidWorks IGES file usi' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\p. |  |
| E7 p.eprt | PASS | bytes=11054 hdr=b'[\x01\x00\x00\x00\xbe\r2008+ archive\x00\x00\x00\x00' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\p. |  |
| E7 p.tif | PASS | bytes=6724067 hdr=b'II*\x00\x06\x99f\x00\xfa\xfa\xfb\xfd\xfd\xfd\xfd\xfd\xfd\xfd\xfd\xfd\xfd\xfd\xfd\xfd' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\p. |  |
| E7 p.png | PASS | bytes=801963 hdr=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x07m\x00\x00\x04\x9b' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\p. |  |
| E7 p.jpg | PASS | bytes=231735 hdr=b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x00\x01\x00`\x00`\x00\x00\xff\xfe\x00\x1f' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\p. |  |
| E7 p.bmp | PASS | bytes=2764854 hdr=b'BM60*\x00\x00\x00\x00\x006\x00\x00\x00(\x00\x00\x00\x00\x05\x00\x00\xd0\x02' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\p. | BMP: Extension.SaveAs rejects .bmp (error 256); use IModelDoc2.SaveBMP 1280x720 |
| E7 p.3mf | PASS | bytes=30073 hdr=b'PK\x03\x04\x14\x00\x00\x00\x08\x001\xa7J]\x14\x87b\xc1\x0c\x17\x00\x00\x91\xb1' {'names': ['3D/3dmodel.model', 'Metadata/thumbnail.png', '[Content_Types].xml', '_rels/.rels'], 'verts': 327, 'tris': 644, 'objects' |  |
| E8 3D PDF | PASS | bytes=9745 U3D=False PRC=True msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\p3d.pdf. |  |
| E8b PDF pdf_3d=false | PASS | bytes=599694 msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\p2d.pdf. |  |
| E-rej option rejected for STEP | PASS | Option 'units' is not supported for STEP (supported: ['step_version']). |  |
| E-rej OBJ unsupported | PASS | EXC RuntimeError('Unsupported output extension. Allowed: .3mf, .bmp, .easm, .eprt, .iges, .igs, .jpe |  |
| E9 configuration export + restore | PASS | active after=Default; Short zmax=10.0 Default zmax=20.0; vol short=6000.0 default=12283.1853 |  |
| E9b unknown configuration refused | PASS | EXC RuntimeError("No configuration named 'Nope'. Available: ['Default', 'Short'].") |  |
| E10 multi-body part has 3 bodies | PASS | ['Bd1', 'Bd0', 'Bd2'] vol=18000.0 | export_bodies rewritten: IBody2.Save takes an IStream; now select body (SOLIDBODY) + Extension.SaveAs; formats x_t,x_b,step,sat,iges,stl |
| E10 export_bodies x_t | PASS | Exported 3 of 3 bodies. files=[('Bd0.x_t', 5413), ('Bd1.x_t', 5421), ('Bd2.x_t', 5389)] hdr=b'**ABCDEFGHIJKLMN' | export_bodies rewritten: IBody2.Save takes an IStream; now select body (SOLIDBODY) + Extension.SaveAs; formats x_t,x_b,step,sat,iges,stl |
| E10 export_bodies x_b | PASS | Exported 3 of 3 bodies. files=[('Bd0.x_b', 5318), ('Bd1.x_b', 5318), ('Bd2.x_b', 5318)] hdr=b'**ABCDEFGHIJKLMN' | export_bodies rewritten: IBody2.Save takes an IStream; now select body (SOLIDBODY) + Extension.SaveAs; formats x_t,x_b,step,sat,iges,stl |
| E10b export_bodies body_names subset | PASS | Exported 1 of 1 bodies. | export_bodies rewritten: IBody2.Save takes an IStream; now select body (SOLIDBODY) + Extension.SaveAs; formats x_t,x_b,step,sat,iges,stl |
| E10c export_bodies 3mf refused (selection ignored) | PASS | Per-body export supports ['.iges', '.igs', '.sat', '.step', '.stl', '.stp', '.x_b', '.x_t'] only; us | export_bodies rewritten: IBody2.Save takes an IStream; now select body (SOLIDBODY) + Extension.SaveAs; formats x_t,x_b,step,sat,iges,stl |
| E10d multi-body STEP | PASS | bytes=36708 | export_bodies rewritten: IBody2.Save takes an IStream; now select body (SOLIDBODY) + Extension.SaveAs; formats x_t,x_b,step,sat,iges,stl |
| E11 3MF multi-body part | PASS | {'names': ['3D/3dmodel.model', 'Metadata/thumbnail.png', '[Content_Types].xml', '_rels/.rels'], 'verts': 24, 'tris': 36, 'objects': 4} |  |
| E11b STL multibody single_file=False | PASS | files=['mb_stl_sep.STL'] |  |
| E11c STL multibody single_file=True | PASS | {'binary': False, 'tri': 36, 'min': [0.0, 0.0, 0.0], 'max': [120.0, 20.0, 20.0], 'bytes': 10196} |  |
| E5d int/toggle prefs restored after all (doubles scale with the active model, compared only in-document) | PASS | {'step_ap': 203, 'stl_quality': 3, 'stl_units': 0, 'vrml_units': 2, 'vrml_ver': 2, 'stl_dev': 7.061184424935825e-06, 'stl_ang': 0.174532925199433, 'stl_bin': True, 'stl_nt': False, 'stl_one': False, 'vrml_one': True} | STL quality/deviation/angle restored as a group (custom quality cannot be set directly); VRML version 0 restores as 2; readback verified |
| E10e per-body x_b contents differ | PASS | {'Bd0.x_b': 'a8e747d2', 'Bd1.x_b': 'f79548fe', 'Bd2.x_b': 'b0ebf547'} | export_bodies rewritten: IBody2.Save takes an IStream; now select body (SOLIDBODY) + Extension.SaveAs; formats x_t,x_b,step,sat,iges,stl |
| E10f export_bodies stl (per-body bbox 20x20x(10,15,20)) | PASS | {'Bd0.STL': [20.0, 20.0, 10.0], 'Bd1.STL': [20.0, 20.0, 15.0], 'Bd2.STL': [20.0, 20.0, 20.0]} | export_bodies rewritten: IBody2.Save takes an IStream; now select body (SOLIDBODY) + Extension.SaveAs; formats x_t,x_b,step,sat,iges,stl |
| E10g export_bodies step AP214 | PASS | [('Bd0.step', 14563), ('Bd1.step', 14563), ('Bd2.step', 14540)] | export_bodies rewritten: IBody2.Save takes an IStream; now select body (SOLIDBODY) + Extension.SaveAs; formats x_t,x_b,step,sat,iges,stl |
| final docs == baseline | PASS | [] vs [] |  |
| A0 Cfg part: Default vol 5000-... vs Short | PASS | default=5570.7963 short=4000.0 |  |
| A0 parts saved | PASS | {'Plate': 46865, 'Block': 46616, 'Pin': 68345, 'Bracket': 53261, 'Cfg': 83119, 'CfgCopy': 70145} |  |
| A0b build Sub.sldasm (plate + pin) | PASS | mate=Added a coincident mate. size=49806 |  |
| A1 insert plate | PASS | Plate-1 origin=[0.0, 0.0, 0.0] cfg=Default is_asm=False |  |
| A1 insert bracket | PASS | Bracket-1 origin=[150.0, 0.0, 0.0] cfg=Default is_asm=False |  |
| A1 insert block | PASS | Block-1 origin=[150.0, 100.0, 0.0] cfg=Default is_asm=False |  |
| A1 insert block2 | PASS | Block-2 origin=[0.0, 100.0, 0.0] cfg=Default is_asm=False |  |
| A1 insert plate2 | PASS | Plate-2 origin=[-150.0, 0.0, 0.0] cfg=Default is_asm=False |  |
| A1 insert pin | PASS | Pin-1 origin=[0.0, -100.0, 0.0] cfg=Default is_asm=False |  |
| A1b list_components fields | PASS | {"name": "Plate-1", "path": "C:\\_Projects\\solidworks-mcp\\sandbox\\phase5\\batchA\\asm\\Plate.sldprt", "suppressed": false, "fixed": true, "configuration": "Default", "depth": 0, "hidden": false, "virtual": false, "suppression_s |  |
| A2a add_mate entities coincident (bracket foot on plate top) | PASS | Added a coincident mate. mate=Coincident1 bracket origin=[0.0, 30.0, 10.0] |  |
| A2b parallel mate | PASS | Added a parallel mate. bracket -z face normal=[-1.0, 0.0, 0.0] |  |
| A2c distance 15 mate | PASS | Added a distance mate. warn=None bracket x=55.0 dims=[{'name': 'D1', 'full_name': 'D1@Distance1@Assem29.Assembly', 'value_mm': 15.0}] |  |
| A2d perpendicular mate | PASS | Added a perpendicular mate. warn=None flange n=[0.0, -1.0, 0.0] |  |
| A3 list_mates details | PASS | [{"name": "Coincident1", "feature_type": "MateCoincident", "suppressed": false, "mate_type": "coincident", "alignment": "anti_aligned", "flipped": false, "min_variation": 0.0, "max_variation": 0.0, "entities": [{"component": "Plat |  |
| A3b check_errors after 4 mates | PASS | No feature errors or warnings. |  |
| A4a distance mate dimension | PASS | D1@Distance1 15.0 | dimension_name now 'D1@<mate>' (2017 reports bare 'D1') |
| A4b edit_mate distance 20 (value only) | PASS | Set mate 'Distance1'. x=60.0 |  |
| A4c set_dimension agrees with edit_mate (back to 15) | PASS | Set D1@Distance1. x=55.0 | dimension_name now 'D1@<mate>' (2017 reports bare 'D1') |
| A5a edit_mate flip=True (re-create): flipped state set, bracket moves to the other side | PASS | Edited mate 'Distance1' (re-created as 'Distance1'). flipped=True x=25.0 (was 55) | edit_mate: EditMate4 is a no-op on 2017; flip/alignment/limits re-create the mate from its entity references (restores original on failure, keeps name) |
| A5b edit_mate flip=False back | PASS | Edited mate 'Distance1' (re-created as 'Distance1'). flipped=False x=55.0 align=anti_aligned dist=15.0 | edit_mate: EditMate4 is a no-op on 2017; flip/alignment/limits re-create the mate from its entity references (restores original on failure, keeps name) |
| A5d edit_mate alignment=aligned | PASS | Edited mate 'Distance1' (re-created as 'Distance1'). align=aligned x=25.0 | edit_mate: EditMate4 is a no-op on 2017; flip/alignment/limits re-create the mate from its entity references (restores original on failure, keeps name) |
| A5c check_errors after edits | PASS | No feature errors or warnings. | edit_mate: EditMate4 is a no-op on 2017; flip/alignment/limits re-create the mate from its entity references (restores original on failure, keeps name) |
| A6a set_mate_suppression suppress | PASS | Suppressed 1 mates. x=55.0 |  |
| A6b unsuppress | PASS | Unsuppressed 1 mates. x=55.0 |  |
| A7a plate2 y-face coincident to plate1 y-face | PASS | Added a coincident mate. origin=[-80.0, 0.0, 0.0] |  |
| A7b angle mate 30 deg | PASS | Added a angle mate. measured angle between top normals=30.000; dims=[{'name': 'D1', 'full_name': 'D1@Angle1@Assem29.Assembly', 'value_deg': 30.0}] list=[(30.0, 'D1@Angle1')] |  |
| A7c edit_mate angle 45 | PASS | Set mate 'Angle1'. measured=45.000 |  |
| A8a block1 on plate top | PASS | Added a coincident mate. origin=[50.0, 33.333333, 10.0] |  |
| A8b limit distance mate | PASS | Added a distance mate. warn=None block x=20.0; min/max var=-0.005/0.005 dims=[{'name': 'D1', 'full_name': 'D1@LimitDistance1@Assem29.Assembly', 'value_mm': 10.0}] |  |
| A8c move beyond max limit: solver keeps within 15..25 | PASS | Moved 'Block-1'. warn=The component did not land where requested; mates are probably constraining it. Suppress or edit the mates (set_mate_suppression / edit_mate) to move it freely. x after=20.0 |  |
| A9a width mate centered (marks 1/2) | PASS | Added a width mate. warn=None block2 x=0.0 | width mate: tab faces must carry selection mark 16 (add_mate maps mark 2 to 16) |
| A9b width_option=dimension | PASS | Added a width mate. warn=None block2 x=-18.0 dims=[{'name': 'D1', 'full_name': 'D1@Width2@Assem29.Assembly', 'value_mm': 12.0}] | width mate: tab faces must carry selection mark 16 (add_mate maps mark 2 to 16) |
| A9b width_option=free | PASS | Added a width mate. warn=None block2 x=-18.0 dims=[] | width mate: tab faces must carry selection mark 16 (add_mate maps mark 2 to 16) |
| A9b width_option=percent | PASS | Added a width mate. warn=None block2 x=-30.0 dims=[{'name': 'D1', 'full_name': 'D1@Width4@Assem29.Assembly', 'value_mm': 0.0}] | width mate: tab faces must carry selection mark 16 (add_mate maps mark 2 to 16) |
| A10a move_component relative on floating pin | PASS | [0.0, -100.0, 0.0]->[30.0, -100.0, 5.0] Moved 'Pin-1'. |  |
| A10b move absolute | PASS | [0.0, -100.0, 0.0] |  |
| A10c rotate_component x 90 (pin axis z -> -y) | PASS | axis=[0.0, -1.0, 0.0] origin=[0.0, -100.0, 0.0] |  |
| A10d rotate about vector with pivot | PASS | origin=[70.710678, -70.710678, -0.0] |  |
| A10e move fixed component refused | PASS | Component 'Plate-1' is fixed; unfix it first (set_component_fixed fixed=false). |  |
| A10f move mated component: warns / solver | PASS | Moved 'Bracket-1'. warn=The component did not land where requested; mates are probably constraining it. Suppress or edit the mates (set_mate_suppression / edit_mate) to move it freely. x=55.0 |  |
| A8d edit_mate limits 3..20 (distance 10 kept) | PASS | Edited mate 'LimitDistance1' (re-created as 'LimitDistance1'). var=-0.007/0.01 block x=20.0 |  |
| A11a hide component | PASS | Hid 1 components. hidden=True vol 136356.1945->136356.1945 |  |
| A11b show component | PASS | Showed 1 components. |  |
| A11c suppress component: volume drops by pin volume | PASS | Suppressed 1 components. state=suppressed dvol=2356.19 (exp 2356.19) |  |
| A11d unsuppress (resolved state) | PASS | Resolved 1 components. state=resolved vol=136356.1945 |  |
| A12a insert .sldasm as subassembly | PASS | Sub-1 is_asm=True origin=[0.0, -250.0, 0.0] children=['Sub-1/Plate-1', 'Sub-1/Pin-1'] |  |
| A12b top_level_only excludes children | PASS | ['Pin-1', 'Plate-2', 'Plate-1', 'Sub-1', 'Block-1', 'Block-2', 'Bracket-1'] |  |
| A12c move subassembly | PASS | [20.0, -250.0, 0.0] |  |
| A12d rotate subassembly | PASS | x axis ->[0.0, 1.0, 0.0] |  |
| A12e hide subassembly | PASS | Hid 1 components. |  |
| A12f suppress subassembly: volume drops by sub volume | PASS | Suppressed 1 components. dvol=50356.19 exp=50356.19 |  |
| A12g unsuppress subassembly | PASS | vol=186712.389 |  |
| A13 save main assembly | PASS | 51471 |  |
| A13b check_errors main | PASS | No feature errors or warnings. |  |
| X1 assembly STEP AP214 | PASS | schema= 'AUTOMOTIVE_DESIGN'  assembly-usage records=9 bytes=69457 |  |
| X1b assembly STEP AP203 | PASS | schema= 'CONFIG_CONTROL_DESIGN'  |  |
| X2a assembly STL single_file=True | PASS | {'tri': 992, 'binary': False, 'min': [1.054821, 2.899997, 0.2353381], 'max': [201.9961, 382.9, 83.76905]} |  |
| X2b assembly STL single_file=False writes one file per component | PASS | 16 files e.g. ['m_sep - Block-1-1.STL', 'm_sep - Block-1.STL', 'm_sep - Block-2-1.STL'] |  |
| X2c prefs restored after assembly STL | PASS | {'step_ap': 203, 'stl_quality': 3, 'stl_units': 0, 'vrml_units': 2, 'vrml_ver': 2, 'stl_dev': 2.508010975896887e-05, 'stl_ang': 0.174532925199433, 'stl_bin': True, 'stl_nt': False, 'stl_one': False, 'vrml_one': True} |  |
| X3 assembly 3MF | PASS | {'names': ['3D/3dmodel.model', 'Metadata/thumbnail.png', '[Content_Types].xml', '_rels/.rels'], 'verts': 259, 'tris': 500, 'objects': 10} |  |
| X4 assembly m.x_t | PASS | bytes=19775 hdr=b'**ABCDEFGHIJKLMNOPQR' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\asm\m.x_t. |  |
| X4 assembly m.sat | PASS | bytes=53373 hdr=b'2200 0 8 0          ' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\asm\m.sat. |  |
| X4 assembly m.igs | PASS | bytes=101024 hdr=b'SolidWorks IGES file' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\asm\m.igs. |  |
| X4 assembly m.easm | PASS | bytes=11671 hdr=b'[\x01\x00\x00\x00\xbe\r2008+ archive' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\asm\m.easm. |  |
| X4 assembly m.png | PASS | bytes=938717 hdr=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x07\x8d' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\asm\m.png. |  |
| X4 assembly m.tif | PASS | bytes=7028617 hdr=b'II*\x00\xac>k\x00\xfa\xfa\xfb\xfd\xfd\xfd\xfd\xfd\xfd\xfd\xfd\xfd' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\asm\m.tif. |  |
| X4 assembly m.bmp | PASS | bytes=2764854 hdr=b'BM60*\x00\x00\x00\x00\x006\x00\x00\x00(\x00\x00\x00\x00\x05' msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\asm\m.bmp. | BMP: Extension.SaveAs rejects .bmp (error 256); use IModelDoc2.SaveBMP 1280x720 |
| X4 assembly m.wrl | PASS | hdr=b'#VRML V1.0 ascii\r\nSe' |  |
| X5 assembly 3D PDF | PASS | bytes=12398 PRC=True msg=Exported document to C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\export\asm\m3d.pdf. |  |
| X6 .eprt refused for assembly | PASS | eDrawings part export is not available for this document type. |  |
| X7 export_components step: distinct, suppressed skipped | PASS | files=['Block.step', 'Bracket.step', 'Plate.step', 'Sub.step'] skipped=[{'component': 'Pin-1', 'reason': 'suppressed'}] msg=Exported 4 of 4 components. | export_components: activate each part before saving (STL exported the whole assembly otherwise); lightweight components are resolved, not skipped |
| X8 export_components stl: per-part bbox | PASS | files=['Block.STL', 'Bracket.STL', 'Pin.STL', 'Plate.STL', 'Sub.STL'] bbox={'Block': [20.0, 20.0, 10.0], 'Bracket': [60.0, 50.0, 30.0], 'Pin': [10.0, 10.0, 30.0], 'Plate': [80.0, 60.0, 10.0], 'Sub': [80.0, 70.0, 40.0]} skipped=[]  | export_components: activate each part before saving (STL exported the whole assembly otherwise); lightweight components are resolved, not skipped |
| X8b prefs restored after export_components | PASS |  | export_components: activate each part before saving (STL exported the whole assembly otherwise); lightweight components are resolved, not skipped |
| X9 export_components pdf refused | PASS | PDF and image formats are not supported for per-component export; use export_document. |  |
| X10 export_components x_t all levels | PASS | files=['Block.x_t', 'Bracket.x_t', 'Pin.x_t', 'Plate.x_t', 'Sub.x_t'] skipped=[] | export_components: activate each part before saving (STL exported the whole assembly otherwise); lightweight components are resolved, not skipped |
| X11 export_components configuration refused | PASS | Components export in their referenced configuration; 'configuration' is not supported here. |  |
| final docs == baseline | PASS | [] vs [] |  |
| C1 insert with configuration | PASS | Cfg-1=Default Cfg-2=Short reported=Short | insert_component: AddComponent5 option 2 creates a new config (fails); use option 0 and set ReferencedConfiguration when it differs |
| C2 mass matches configurations | PASS | vol=57570.7963 expected=57570.80 | insert_component: AddComponent5 option 2 creates a new config (fails); use option 0 and set ReferencedConfiguration when it differs |
| C3a set_component_configuration Default->Short | PASS | Set Cfg-1 to configuration 'Short'. vol=56000.0 cfg=Short | insert_component: AddComponent5 option 2 creates a new config (fails); use option 0 and set ReferencedConfiguration when it differs |
| C3b back to Default | PASS | vol=57570.7963 | insert_component: AddComponent5 option 2 creates a new config (fails); use option 0 and set ReferencedConfiguration when it differs |
| C3c unknown configuration refused | PASS | 'Nope' is not a configuration of Cfg-1. Available: ['Default', 'Short'] | insert_component: AddComponent5 option 2 creates a new config (fails); use option 0 and set ReferencedConfiguration when it differs |
| C4a mate before replace | PASS | Added a coincident mate. mates=1 |  |
| C4b replace_component keeps mates (ReplaceComponents2 arg order) | PASS | Replaced 'Cfg-1' with CfgCopy.sldprt. new=CfgCopy-1 path=C:\_Projects\solidworks-mcp\sandbox\phase5\batchA\asm\CfgCopy.sldprt mates 1->1 suppressed=[False] errors=No feature errors or warnings. data={"component": "Cfg-1", "new_pat |  |
| C4c replaced component sits on plate (mate alive) | PASS | origin=[50.0, 0.0, 10.0] |  |
| C5 open_component | PASS | Opened Cfg.sldprt. active=None docs=['Plate.sldprt', 'Cfg.sldprt', 'CfgCopy.sldprt', 'Assem30'] |  |
| I1 overlapping blocks: one interference of 2000 mm3 | PASS | Found 1 interferences. {'interferences': [{'components': ['Block-1', 'Block-2'], 'volume_mm3': 2000.0, 'possible': False}], 'count': 1, 'total_volume_mm3': 2000.0} |  |
| I2 SW left out of the checker (doc ops still work) | PASS | No feature errors or warnings. / Read active document. |  |
| I3 touching faces: none by default | PASS | {'interferences': [], 'count': 0, 'total_volume_mm3': 0} |  |
| I4 touching faces: coincidence flag | PASS | count=1 [{'components': ['Block-1', 'Block-2'], 'volume_mm3': 0.0, 'possible': False}] |  |
| I5 separated blocks: none | PASS | {'interferences': [], 'count': 0, 'total_volume_mm3': 0} |  |
| I6 offset overlap volume | PASS | {'interferences': [{'components': ['Block-1', 'Block-2'], 'volume_mm3': 1500.0, 'possible': False}], 'count': 1, 'total_volume_mm3': 1500.0} expected 1500 |  |
| I7 ignore_hidden_bodies drops hidden pair | PASS | {'interferences': [], 'count': 0, 'total_volume_mm3': 0} |  |
| final docs == baseline | PASS | [] vs [] |  |
| F12 dialog guard: toggles 10/77 off inside, restored; erroring feature returns without a dialog | PASS | before=(True, True) inside=(False, False) after=(True, True) after-bad-feature=(True, True); SOLIDWORKS did not create the boss extrusion. Check that the required selection  |  |
| X12 export_components on lightweight components resolves and exports them | PASS | states={'lightweight'} files=['Block.step', 'Bracket.step', 'Pin.step', 'Plate.step', 'Sub.step'] skipped=[] | export_components: activate each part before saving (STL exported the whole assembly otherwise); lightweight components are resolved, not skipped |
| C6 replace_component with configuration=Short keeps mate | PASS | Replaced 'CfgCopy-1' with Cfg.sldprt. new=Cfg-1 cfg=Short vol=52000.0 origin=[50.0, 0.0, 10.0] | insert_component: AddComponent5 option 2 creates a new config (fails); use option 0 and set ReferencedConfiguration when it differs |
| C5b open_component makes the part the active document | PASS | active title=Cfg.sldprt |  |
| final docs == baseline | PASS | [] vs [] |  |
