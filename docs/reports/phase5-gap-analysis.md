# Phase 5 gap analysis: missing capabilities (parts, assemblies, export)

Scope: 3D parts and assemblies; drawings deferred. Offline analysis of the 95 existing tools against `tools/compat/sw2017_api_members.txt`.
Legend: API column = member present in the 2017 snapshot (OK) or **ABSENT**. Complexity S/M/L. "Verify" = live measurement.
Enum values (swUserPreference_e, swExportDataFileType_e, swMateType_e extras, etc.) are not in the member snapshot; confirm each against the typelib enum dump before coding.

## 0. Current state in brief

- `export_document` takes only `path` and `overwrite`; the format is chosen by extension from `EXPORT_EXTENSIONS` = step, stp, iges, igs, stl, x_t, x_b, png, jpg, bmp, 3mf. It always calls `IModelDocExtension.SaveAs(path, 0, 0, Nothing, errors, warnings)`. No export data object, no options, no per-body or per-component export.
- 3MF: `_save_as` already tolerates it. 2017 SP5 writes a valid zip but returns False and error code 1 (swGenericSaveError), and the code accepts that when the file starts with "PK". The probable cause is that 3MF export in 2017 is a newer, incomplete add-in path. It ignores `swSaveAsOptions_Silent` and reports failure even when it wrote the file. Residual risk: multi-body or assembly 3MF may write nothing. No further fix is needed beyond live-checking assemblies. If 3MF is "known failing" for another reason, the first thing to find out is the exact failing document type (part, assembly or multi-body).
- Assembly: `insert_component`, `add_mate` (coincident, concentric, perpendicular, parallel, tangent, distance, angle, symmetric, width, lock, slot, profile_center), `list_mates`, `delete_mate`, `list_components`, `set_component_fixed`.
- Part features: extrude/cut, revolve, sweep, loft, fillet, chamfer, shell, draft, rib, simple_hole, linear/circular pattern, mirror_feature, set_feature_suppression, delete/rename feature. Reference geometry: `create_plane`, `create_axis`. Inspection: `list_faces/edges/vertices/bodies`, `measure`, `get_mass_properties`, `get_bounding_box`.
- Not present at all: configurations, equations, custom properties, undo, component move/hide/replace, interference, exploded views, hole wizard, split/combine, scale, move/copy body, helix, coordinate systems, sheet metal, selection helpers.

## 1. Export (Batch A priority)

Design: extend `export_document` rather than add many tools. Add args `format` (optional override of extension), `options` object, `body_names`/`component_names` (per-item export), `units`, `configuration`. Add a read-only `list_export_formats`.

| # | Proposed tool / args | 2017 API needed (status) | Cx | Verify live |
|---|---|---|---|---|
| E1 | `export_document(path, step_version: "AP203"\|"AP214"\|"AP242", ...)` for `.step` | `ISldWorks.GetExportFileData` OK (returns IDispatch; the typed `IExportFileData`/`IStepExportData` interfaces are NOT in the snapshot, so use late binding), `IModelDocExtension.SaveAs` OK, `ISldWorks.SetUserPreferenceIntegerValue` OK (swStepAP = preference). AP242 via `IModelDocExtension.PublishSTEP242File` OK exists but is MBD-oriented; treat AP242 as unverified. | M | Header of file: `FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'))` = AP203, `AUTOMOTIVE_DESIGN` = AP214; reimport count of solids and volume within 0.1% |
| E2 | `export_document(.iges, options: {surfaces/solids/wireframe, units})` | `SetUserPreferenceIntegerValue/ToggleValue` OK | M | `S`/`G` section markers in file, entity count; reimport volume |
| E3 | `.x_t` / `.x_b` Parasolid with `parasolid_version` | SaveAs OK (version via `SetUserPreferenceIntegerValue`, enum to confirm) | S | Header `**PART1` text, file nonzero, reimport mass |
| E4 | `.stl` with `format: binary\|ascii`, `quality: coarse\|fine\|custom`, `deviation_mm`, `angle_deg`, `units`, `one_file_per_body`, `coordinate_system` | `SetUserPreferenceIntegerValue`/`DoubleValue`/`ToggleValue` OK (swExportStlBinaryFormat, QualityOption, Units etc. enums to confirm); `ISldWorks.GetUserPreferenceIntegerValue` OK for readback; restore old prefs in `finally` | M | Binary: size = 84 + 50 x triangle count (header int at byte 80); ASCII starts with `solid`; finer quality yields strictly more triangles; bbox from file equals `get_bounding_box` |
| E5 | `.3mf` | existing path; add assembly/multi-body check | S | zip contains `3D/3dmodel.model`; vertex bbox matches |
| E6 | `.obj` | **Not a 2017 SaveAs format** (OBJ export arrived in later releases); do not promise. Document as unsupported; offer STL then convert externally | n/a | try SaveAs `.obj`, expect failure and record it |
| E7 | `.wrl` VRML, `.xaml`/3D XML | SaveAs by extension OK (`.wrl` is supported in 2017); add to `EXPORT_EXTENSIONS` | S | file starts `#VRML V2.0`; size > 0 |
| E8 | `.eprt/.easm/.edrw` eDrawings | SaveAs by extension (eDrawings publisher installed with SW); add to allowlist | S | file exists, size > 0 (fails cleanly if eDrawings not installed) |
| E9 | `.pdf` of the 3D model (3D PDF) | `IExportPdfData` OK: `ExportAs3D`, `ViewPdfAfterSaving`; creation via `ISldWorks.GetExportFileData(swExportPdfData)` OK | M | file begins `%PDF`, contains `/U3D` or `/PRC` stream. Needs the 3D PDF template and may be unavailable; fence if it fails |
| E10 | `.dxf/.dwg` of a face or sheet-metal flat pattern | `IPartDoc.ExportToDWG2` OK, `IPartDoc.ExportFlatPatternView` OK. (`IModelDoc2.ExportToDWG2` ABSENT; use the IPartDoc one.) Face/sketch DXF without a drawing: `SaveAs` of a selected sketch or face to `.dxf` is not reliable; prefer a flat pattern | M | Parse DXF: count of LINE/ARC entities, overall extents match the flat pattern bbox |
| E11 | Images: `.png .jpg .tif .bmp .gif` via `capture_screenshot`/export with `width_px`, `view` | `IModelDoc2.SaveBMP` OK, SaveAs by extension; add `.tif`, `.gif` | S | image header, dimensions equal request |
| E12 | `.sat` (ACIS), `.ipt`-style, `.ifc`, `.hcg/.hsf`, `.prt/.sldprt` copy | SaveAs by extension; `.sat` is the one worth adding | S | file header `ACIS`, reimport |
| E13 | Per-body export: `export_bodies(path, body_names[], format)` | `IBody2.Save` OK (exports a body to file; `IBody2.Save3`, `IBody2.SaveToFile` ABSENT), or `IBody2.Copy` + `IPartDoc.CreateFeatureFromBody3` for a temp part | M | N bodies produce N files; each reimports with volume equal to that body's `list_bodies` volume |
| E14 | Per-component export from assembly: `export_component(component_name, path, format)` | `IComponent2.GetModelDoc2` OK, then SaveAs on the part doc; or `IAssemblyDoc.GetComponentByName` OK | M | Same volume as the part's own mass |
| E15 | Export with units/config: `configuration`, `units` args | `IModelDoc2.ShowConfiguration2` OK; unit prefs via `SetUserPreferenceIntegerValue` | S | Bbox in file scaled correctly (mm vs inch) |
| E16 | Assembly-specific: `export_document` of an assembly as single merged body vs multiple (STEP `export as assembly`) | preference toggles (to confirm) | M | Reimport: solid count equals component count or 1 |

Common rule for all E-tools: write only under `sandbox/`; verify with file size plus a header or content check plus reimport measurement.

## 2. Assemblies (Batch A essentials, Batch C advanced)

| # | Tool / args | API (status) | Cx | Verify |
|---|---|---|---|---|
| A1 | `list_mates` upgrade: return mate name, type name, alignment, suppressed, entities, dimension name (e.g. `D1@Distance1`) and value | `IMate2.Type, Alignment, MateEntity, GetMateEntityCount, MaximumVariation, MinimumVariation, DisplayDimension2` OK; `IMate2.Name/GetTypeName/Suppressed` ABSENT (get the name from the owning `IFeature.Name`, suppression via `IFeature.IsSuppressed2` OK) | M | Add distance mate 12 mm, list returns it with dimension name and value 12 |
| A2 | `edit_mate(name, distance_mm?, angle_deg?, flip?, alignment?, min/max)` | Edit dimension via `IDimension.SetSystemValue3` (existing `set_dimension` logic) OK; flip/align: `IFeature.GetDefinition`/`ModifyDefinition` OK (`IMateFeatureData` typed interface ABSENT, late-bind) ; limits: `IMate2.MinimumVariation/MaximumVariation` OK | M | Component position measured by `measure` between faces changes by the delta |
| A3 | `set_mate_suppression(names, suppressed)` | `IFeature.SetSuppression2` OK (existing `set_feature_suppression` may already work for mate features; just verify and document) | S | Component translates when a mate is suppressed; `IsSuppressed2` readback |
| A4 | Advanced mates: `add_mate` types `limit_distance`, `limit_angle` (min/max), `gear`, `rack_pinion`, `screw`, `hinge`, `universal_joint`, `cam`, `path`, `linear_coupler` | `AddMate5` OK with extra args (MinDist/MaxDist/ GearRatio numerator/denominator, `SmartMates`); types in swMateType_e (confirm numbers; `width`, `slot`, `profile_center` already mapped, but check width/slot need multiple-entity selection marks) | L | Gear: rotating one component by angle X moves the other by X * ratio (read transforms); limit: drive via `SetTransformAndSolve2`-style move to exceed limit and confirm clamp |
| A5 | Mate selection helper accepting component name + face/edge index (not only selection spec) | `IComponent2.Select4`, `IEntity.Select4`, `IModelDocExtension.SelectByID2` OK | M | Mate created without raw coordinates |
| A6 | `insert_subassembly` (existing assembly file as component) | `AddComponent5` OK (same as insert_component; verify accepts .sldasm, existing tool may already) | S | `list_components` shows child components of subassembly |
| A7 | `new_subassembly(name, path)` (virtual or in-context new assembly) | `InsertNewVirtualAssembly` OK, `MakeAssemblyFromSelectedComponents` OK, `MakeIndependent` OK | M | Component tree depth increases; file saved if non-virtual |
| A8 | `set_component_configuration(component, config)` and `list_component_configurations` | `IComponent2.ReferencedConfiguration` OK (put), `IAssemblyDoc.AddComponentConfiguration` OK, `ISldWorks`/`IModelDoc2.GetConfigurationNames` OK | S | Mass changes to match that configuration's mass |
| A9 | `replace_component(old, new_path, keep_mates)` | `IAssemblyDoc.ReplaceComponents2` OK | M | `list_components` path updated; mate count preserved |
| A10 | `pattern_components` (linear, circular, derived, mirror) | Component patterns: `IFeatureManager.InsertDerivedPattern(2)`, `IAssemblyDoc.InsertDerivedPattern`, `MirrorComponents3`/`MirrorComponents2`, `DissolveComponentPattern` OK. **ABSENT** in this snapshot: `IFeatureManager.InsertLinearComponentPattern/InsertCircularComponentPattern` (so the linear/circular component pattern is likely done via `IFeatureManager.FeatureLinearPattern5`/`FeatureCircularPattern5` with component selection, unverified, or by derived pattern) | L | Component count rises by N; transforms spaced as specified |
| A11 | `check_interference(components?, treat_coincident, include_multibody)` returning pairs + volume | `IAssemblyDoc.InterferenceDetectionManager` OK, `IInterferenceDetectionMgr.GetInterferences/IncludeMultibodyPartInterferences/TreatCoincidenceAsInterference/Done` OK, `IInterference.Volume/Components/IsPossibleInterference` OK; also `ToolsCheckInterference2` OK. Must call `Done()` or a dialog may stay open | M | Two overlapping boxes of known overlap volume V: reported volume = V within 0.1% ; separated boxes: zero |
| A12 | `explode_assembly(steps[])`, `collapse`, `list_exploded_views` | `IAssemblyDoc.CreateExplodedView`, `ShowExploded2`, `GetExplodedViewNames2`, `EditExplodeParameters`, `AutoExplode`, `IConfiguration.AddExplodeStep` OK; `AddExplodeStep2` ABSENT | L | `IsExploded` true; component transform differs by the step distance |
| A13 | `open_component(name)` (open part from assembly in its own window) | `IComponent2.GetModelDoc2`, `ISldWorks.OpenDoc6`, `IAssemblyDoc.EditPart2` OK | S | `list_open_documents` includes it; active doc title matches |
| A14 | `set_component_visibility(names, visible)`, `set_component_suppression`, `set_component_transparency` | `IAssemblyDoc.HideComponent/ShowComponent` OK, `HideComponent2`/`ShowComponent2` are on `IModelDoc2` OK, `SetComponentVisibility`, `SetComponentSuppression`, `SetComponentTransparent` OK | S | Component `Visible` readback; mass unchanged for hide, changes for suppress |
| A15 | `move_component(name, dx,dy,dz)` / `rotate_component(name, axis, angle)` / `set_component_transform(name, matrix)` | `IAssemblyDoc.TranslateComponent`, `RotateComponentAxis`, `RotateComponent`; `IComponent2.SetTransformAndSolve2`, `Transform2` OK; `IMathUtility.CreateTransform` OK (existing code) | M | `Transform2` read back equals request; floating (unmated) component only |
| A16 | `remove_component(name)` | `IAssemblyDoc.RemoveComponent`? (use `IModelDocExtension.DeleteSelection2` OK after `Select4`) | S | Component count decrements |
| A17 | Assembly features: assembly cut/hole, `InsertJoin2`, `InsertCavity4`, smart fasteners | OK members exist | L | volume of target part reduced |
| A18 | `get_component_info(name)`: path, config, fixed, virtual, suppressed, lightweight, transform, children | Mostly OK; `IAssemblyDoc.ResolveAllLightWeightComponents` OK | S | values consistent with other tools |
| A19 | `get_assembly_mass` / BOM-ish quantity roll-up | `GetMassProperties2` OK | S | equals sum of component masses |

## 3. Parts

| # | Tool / args | API (status) | Cx | Verify |
|---|---|---|---|---|
| P1 | Configurations: `list_configurations`, `add_configuration(name, desc)`, `activate_configuration(name)`, `delete_configuration`, `set_config_suppression(feature, config)` | `IModelDoc2.GetConfigurationNames`, `AddConfiguration3`, `ShowConfiguration2`, `DeleteConfiguration2`, `GetActiveConfiguration`, `IConfigurationManager.AddConfiguration` OK; `IConfigurationManager.AddConfiguration2` ABSENT | M | Config list grows; per-config mass differs after suppressing a feature in one |
| P2 | Design tables: `insert_design_table(excel_path)`, `get_design_table` | `IModelDoc2.InsertFamilyTableNew/Edit/Open`, `GetDesignTable`, `DeleteDesignTable` OK; `IModelDocExtension.InsertDesignTable` ABSENT (the Excel route needs Excel installed: defer) | L | Configs created equal table rows |
| P3 | Equations / global variables: `list_equations`, `set_equation(name, expr)`, `add_global_variable(name, value)`, `delete_equation` | `IModelDoc2.GetEquationMgr`, `IEquationMgr.Add3/Add2/Equation/Value/GlobalVariable/EvaluateAll/Delete/GetCount/Status` OK; PROPGET-with-args: must route through `flag_methods` (see CLAUDE.md) | M | Dimension driven by `"D1@Sketch1" = "w"*2` changes bbox on global var edit |
| P4 | Custom properties: `get/set/delete_custom_properties(config?)`, `list` | `IModelDocExtension.CustomPropertyManager` (property, takes config string; late-bind carefully), `ICustomPropertyManager.Add3, Get5, Set2, Delete2, GetNames` OK; `GetAll3` ABSENT (loop over `GetNames` + `Get5`) | M | Write then read back; save/reopen file and read again |
| P5 | Reference geometry: `create_point` (xyz, on-vertex, on-edge), `create_coordinate_system(origin, axes)`, plane variants (already partly) | `IFeatureManager.InsertReferencePoint`, `IModelDoc2.InsertRefPoint`, `IFeatureManager.CreateCoordinateSystem/InsertCoordinateSystem`, `IModelDoc2.InsertCoordinateSystem`, `IModelDocExtension.GetCoordinateSystemTransformByName` OK; `IFeatureManager.InsertRefPoint` ABSENT (use InsertReferencePoint) | M | Point position read from `IRefPoint.GetRefPoint`; coord sys transform read back |
| P6 | Sheet metal basics: `sheet_metal_base_flange`, `edge_flange`, `miter_flange`, `hem`, `jog`, `fold/unfold`, `flat_pattern`, `convert_to_sheet_metal` | `IFeatureManager.InsertSheetMetalBaseFlange2`, `InsertSheetMetalEdgeFlange2`, `InsertSheetMetalMiterFlange`, `InsertSheetMetalHem2`, `InsertConvertToSheetMetal2`, `InsertSheetMetal3dBend`, `InsertSheetMetalGussetFeature3`, `InsertSheetMetalCornerTrim`, `IPartDoc.InsertBends2`, `IModelDoc2.InsertSheetMetalFold/Unfold/Jog/BreakCorner`, `SetBendState` OK (only the older IFeatureManager.InsertSheetMetalBase** variants differ) | L | Flat pattern bbox: length = L1 + L2 - bend deduction (K-factor); mass equals thickness x area x density |
| P7 | Hole Wizard: `hole_wizard(type, standard, size, end_condition, depth, cbore/csink params)` | `IFeatureManager.HoleWizard5` OK (and 2..4, `IModelDoc2.HoleWizard`) | L | Cylindrical face count/diameter via `list_faces`; volume removed = expected |
| P8 | Thread: `cosmetic_thread(edge, standard, size, depth)`; modeled thread via sweep/cut helix | `IFeatureManager.InsertCosmeticThread3` OK (2, plain also); real thread needs helix: `IModelDoc2.InsertHelix` OK (`IFeatureManager.InsertHelix` ABSENT) + `InsertVariablePitchHelix` OK | M (cosmetic) / L (modeled) | Feature in tree with thread diameter property; modeled thread volume delta |
| P9 | Split body / combine / delete body | `PreSplitBody2` + `PostSplitBody` OK (`IFeatureManager.InsertSplitBody` ABSENT); `InsertCombineFeature` (add/subtract/common), `IPartDoc.InsertCombineFeature` OK; `InsertDeleteBody2` OK; `IFeatureManager.HideBodies/ShowBodies` OK | M | Body count and sum of volumes before/after |
| P10 | Dome | `IModelDoc2.InsertDome` OK (`IFeatureManager.InsertDome` ABSENT) | S | Bbox height increases by dome height |
| P11 | Wrap (emboss, deboss, scribe) | `InsertWrapFeature2` OK | M | Volume delta for deboss/emboss |
| P12 | Curves: helix, composite curve, curve through XYZ points, projected curve, split line | `IModelDoc2.InsertHelix/InsertCompositeCurve/InsertCurveFile*`, `Insert3DSplineCurve`, `InsertSplitLineProject/Sil`, `InsertSplitLineIntersect` OK; `IModelDoc2.InsertCurveThroughXYZ` ABSENT (use `InsertCurveFile*` pipeline or 3D spline) | M-L | Curve length from `ICurve` vs analytic (helix length = N x sqrt((2 pi r)^2 + p^2)) |
| P13 | Move/copy body, scale, mirror body | `InsertMoveCopyBody2`, `InsertScale`, `IModelDoc2.InsertScale`, `IModelDoc2.Scale`; mirror via existing `mirror_feature` with `mirror_body`; `IPartDoc.MirrorPart2` (mirrors whole part into new doc) OK | M | Body bbox translated by exact delta; scaled volume = s^3 x V |
| P14 | Multi-body: `list_bodies` (exists), `select_body`, `delete_body`, `combine_bodies`, `merge_scope` on features | see P9; features need `FeatureScopeBodies` (typed feature data) | M | Body count |
| P15 | `measure_between(entity_a, entity_b)`: min distance, angle, center-to-center | `IModelDocExtension.CreateMeasure`, `IMeasure.Calculate/Distance/NormalDistance/DeltaX/Y/Z/Angle/ArcLength/Radius/...` OK (verify existing `measure` tool covers selection by names) | S | Known gap between two parallel faces |
| P16 | Section properties: area, centroid, Ixx of a planar face/sketch | `IModelDocExtension.CreateMassProperty` on face selection, or `ISketch`/`ISketchRegion` area; `IFace2.GetArea` OK | M | Rectangle b x h: area = bh, Ixx = bh^3/12 |
| P17 | Mass props with material override: `get_mass_properties(density?, override_mass?, coordinate_system?, bodies?)` | `IMassProperty.OverrideMass`, `SetCoordinateSystem`, `AddBodies`, `UseSystemUnits`, `IncludeMassPropertiesOfHiddenBodies` OK; `IMassProperty.SetBodies/Recalculate` ABSENT (use `AddBodies`); `CreateMassProperty2` ABSENT (known) | M | mass = density x volume; override returns user value |
| P18 | Unit/doc settings: `set_units`, `set_precision`, `set_document_property(name,value)` | `IModelDoc2.SetUnits`, `IModelDocExtension.SetUserPreferenceDouble/Integer/Toggle/String` OK | S | Readback via `GetUserPreference*` |
| P19 | Surface ops commonly mixed with solids: thicken, knit, offset, trim, extend, untrim, fill | `FeatureBossThicken`, `InsertSewRefSurface`, `InsertOffsetSurface`, `PreTrimSurface/PostTrimSurface`, `InsertExtendSurface`, `InsertUntrimSurface`, `InsertFillSurface2`, `InsertMidSurface` OK; `IFeatureManager.InsertBoundaryBoss` ABSENT (boundary via `IBoundaryBossFeatureData` + `CreateDefinition`) | L | Solid created; volume |
| P20 | Features with typed data used for editing: `edit_feature(name, params)` (generic modify definition) | `IFeature.GetDefinition`, `ModifyDefinition`, `IFeatureManager.EditSketch`, existing `set_dimension` OK; **cleanest long-term answer** for "edit anything" | L | Dimension / parameter changes reflected in volume |
| P21 | Variable/other fillets (face, full round, variable radius, setback), chamfer vertex, multi-radius | `FeatureFillet3` OK, `IFeatureManager.FeatureFillet` family; `FilletXpert*` OK | M | Removed volume vs formula |
| P22 | Draft and shell variants: multi-thickness shell, parting-line draft, neutral-plane selection | `InsertMultiThickness` ABSENT; `IFeatureManager.InsertDraft` ABSENT (check what `draft` already calls), `InsertFeatureShell` ABSENT per snapshot (existing `shell` tool presumably uses a different member: confirm in code) | M | Wall thickness via `measure` |

## 4. Robustness

| # | Tool / change | API (status) | Cx | Verify |
|---|---|---|---|---|
| R1 | `undo(count=1)` / `redo` | `IModelDoc2.EditUndo2` OK, `EditRedo2` OK, `ClearUndoList` OK; `IModelDoc2.GetUndoCount`, `IModelDocExtension.EditUndo` ABSENT. Beware: no undo count API, so return feature count/last feature name before and after | S | Feature count decrements; volume restored |
| R2 | Dialog suppression gaps: generalize `dimension_dialog_suppressed` into a context manager used by every feature tool; also set `swUserPreferenceToggle` for "Show errors every rebuild", "Ask to verify...", fillet/shell warnings, `ISldWorks.EnableBackgroundProcessing`, `ISldWorks.CommandInProgress` guard | `ISldWorks.SetUserPreferenceToggle` OK, `SendMsgToUser2` OK (answer prompts), restore in `finally` | M | Run a feature that normally pops a dialog; call returns within timeout, error code reported |
| R3 | Timeout / watchdog: if a call exceeds N seconds, return "possibly modal dialog" with screenshot (`capture_screenshot` already exists) | Python-side thread; Win32 `EnumWindows` to find a dialog caption | M | Induced dialog is reported rather than hanging |
| R4 | Selection helpers: `select_by_name(type, name, component?)`, `select_by_point(x,y,z,type)`, `select_face(body, index)`, `select_feature(name)`, `clear_selection`, `get_selection` | `IModelDocExtension.SelectByID2` OK, `SelectByRay` OK, `MultiSelect2` OK, `IEntity.Select4`, `IFace2.Select4`, `IFeature.Select2`, `IComponent2.Select4`, `ISelectionMgr.GetSelectedObject6/GetSelectionPoint2/SetSelectedObjectMark` OK | M | Selection count and type readback; subsequent feature acts on the selected entity |
| R5 | Stable entity references: return face/edge identity that survives rebuild (persistent ID) | `IModelDocExtension.GetPersistReference3` / `GetObjectByPersistReference3` (confirm in snapshot) | M | Same face found after a rebuild that reorders faces |
| R6 | `get_feature_tree(include_suppressed, dims)` and `get_rebuild_errors` per feature | `IFeature.GetErrorCode2`, `IFeature.IsSuppressed2` OK; `IFeature.GetSuppression2`, `IModelDoc2.GetUndoCount` ABSENT | S | Induce an error, see feature flagged |
| R7 | `rollback_to(feature)` / `roll_forward` (edit insert-point) | `IFeatureManager.EditRollback` OK | S | Feature count visible changes; volume at that stage |
| R8 | Save helpers: `save_as_copy`, `pack_and_go`-lite, `set_document_dirty` | `IModelDocExtension.SaveAs`, `IModelDoc2.SetSaveFlag` OK | S | file present, reopens |
| R9 | Idempotent-read tools: `get_document_properties` (units, mass density, configs, dirty flag), `get_selection_info` | various | S | |

## 5. Existing tools whose args are too limited

| Tool | Gap | Fix |
|---|---|---|
| `boss_extrude` / `cut_extrude` | `end_condition` enum already lists `up_to_surface`, `up_to_vertex`, `offset_from_surface`, `up_to_body`, `mid_plane`, but there is **no way to name the target face/vertex/body** and no offset distance, so these are unusable in practice. No second direction (depth2, end_condition2, draft2), no thin feature, no draft toward the inside on cut (`cut_extrude` has `draft_deg` but no `draft_outward`), no `from` offset (sketch plane / surface / offset), no feature scope (`merge` only), no contour selection. | Add `target_selection`, `offset_mm`, `depth2_mm`, `end_condition2`, `draft2_deg`, `thin: {thickness_mm, type, cap_ends}`, `start_offset_mm`, `contours`, `scope_bodies`. API: `FeatureExtrusionThin2`, `FeatureCutThin` OK, `FeatureExtrusion3`/`FeatureCut4` already accept most of these. |
| `revolve` | No end-condition other than angle / mid_plane; no thin revolve; only one direction angle. | `FeatureRevolve2` params for direction 2, thin; `FeatureRevolveCut2` OK. |
| `fillet` | Constant radius, edge selection only. | Add `type` (face, full_round, variable), setback, multiple radii (`FeatureFillet3` OK). |
| `chamfer` | Edges only, no vertex chamfer. | `InsertFeatureChamfer` OK. |
| `shell` | Single thickness, no multi-thickness faces. | Multi-thickness API is **ABSENT** by name (`InsertMultiThickness`); use `IShellFeatureData`/definition editing (late-bound) or defer. |
| `draft` | Angle + reverse only; no neutral plane type, no step draft, no parting-line draft. | Extend with `neutral_plane`, `pull_direction` selection marks. |
| `simple_hole` | Plain diameter/depth/reverse only. Fine for simple holes; cannot do cbore/csink/tapped. | Add `hole_wizard` (P7). |
| `sweep` / `loft` | No guide curves, no start/end tangency, no twist along path other than `twist_angle_deg`; loft: no centerline, no start/end constraints. | `InsertProtrusionSwept4`, `InsertProtrusionBlend2`/`InsertCutBlend` OK. |
| `linear_pattern` / `circular_pattern` | No seed-feature selection by name (relies on selection), no skipped instances, no direction-from-edge selection, no pattern of bodies, no "vary sketch". | Add `features[]`, `skip_instances[]`, `direction_edge`, `pattern_bodies`. APIs `FeatureLinearPattern5`, `FeatureCircularPattern5`, `FeatureFillPattern`, `FeatureSketchDrivenPattern` OK. |
| `mirror_feature` | Mirrors via selection; plane choice only through selection. | Add `plane`, `features[]`. |
| `insert_component` | Position by x/y/z only: no rotation, no component to-be-fixed, no name override, no virtual-part, no "float vs fix" default. | Add rotation matrix or euler, `fixed`, `copy_as_virtual`. |
| `add_mate` | No limit/min-max, no mate on components by name, no mate-reference, no multi-select (width/slot need 3-4 entities), no `smart mate`, no mate name. | See A1, A2, A4, A5. |
| `list_mates` | No dimension names/values, no suppression state, no entity detail. | A1. |
| `set_material` | By name+database only; no custom density. | Add `custom_density_kg_m3`, per-body material (`IBody2.MaterialPropertyValues` exists, but material name per body needs `IBody2.SetMaterialPropertyName`? not in snapshot: verify). |
| `get_mass_properties` | No density override, coordinate system, bodies subset, hidden-bodies option, per-component in assemblies. | P17. |
| `create_plane` | Offset/angle modes only; missing through-3-points, normal-to-curve-at-point, tangent-to-surface, midplane. | `CreatePlaneAtSurface3`, `CreatePlanePerCurveAndPassPoint3` OK. |
| `create_axis` | Selection-defined only. | Add `from_points`, `from_cylinder_face`, `edge`. |
| `export_document` | See section 1. | |
| `set_view` / `capture_screenshot` | No custom camera, no section view, no display-mode (hidden lines, wireframe), no isolate. | `ShowNamedView2` OK, `ViewDisplay*` family. |
| `list_features` | No dimension/parameter list, no per-feature error state. | R6. |

## 6. Recommended batch plan

Ordering principle: highest user value for the least live risk first; each batch is offline-implemented by Sonnet, then one serial live pass.

### Batch A: exports plus assembly essentials (do first)
1. E1-E5, E7, E8, E11, E15: extend `export_document` (format, options, units, configuration); STL options (E4) first, STEP version (E1) second. Add `list_export_formats`. Record OBJ as unsupported (E6).
2. E13/E14: per-body and per-component export.
3. A1 `list_mates` upgrade, A3 mate suppression, A2 `edit_mate` (distance/angle/flip), A5 name-based mate selection helper, A8 component configuration, A13 `open_component`, A14 visibility/suppression, A15 move/rotate, A16 remove.
4. A11 interference, A9 replace, A6 subassembly insert.
5. R1 undo, R2 dialog-suppression context manager, R4 selection helpers (needed by everything after).
6. Fix the unusable end conditions on extrude/cut (target selection, offset, direction 2, thin) since they are used constantly.
Live pass: one serial session in sandbox; E-tools verified by file headers and reimport measurement, assembly tools by transforms and interference volume.

### Batch B: part features, configurations, properties
P1 configurations, P3 equations/global variables, P4 custom properties, P5 points/coordinate systems, P7 hole wizard, P9 split/combine/delete body, P13 move-copy/scale, P15 measure upgrade, P17 mass props override, P18 units, P21 fillet variants, R6/R7 tree and rollback, create_plane/axis extension, set_material density, pattern argument gaps, E9/E10/E12 (3D PDF, DXF flat pattern, SAT), E16, A7 new subassembly, A12 exploded views (could also move to C).

### Batch C: advanced
A4 advanced mates (gear, rack, screw, limit, cam, path), A10 component patterns, A17 assembly features, P2 design tables, P6 sheet metal suite, P8 modeled threads and helix, P10 dome, P11 wrap, P12 curves, P16 section properties, P19 surfacing, P20 generic `edit_feature` via `GetDefinition/ModifyDefinition`, R3 modal-dialog watchdog, R5 persistent references, shell multi-thickness, sweep/loft guides.

### Open risks to note at the gates
- Typed export-data interfaces (`IExportFileData`, `IStepExportData`) and `IMateFeatureData` are not in the snapshot; they must be driven by late binding or preference toggles, which means each needs a live probe before coding.
- Component pattern, boundary, split-body and multi-thickness shell members are absent by their usual names; implementation should be routed through the alternatives listed, probed live first (tiny scripts under `sandbox/`).
- 3D PDF, eDrawings export and Excel design tables depend on optional installed components; each should degrade to a clear "not available" result.
