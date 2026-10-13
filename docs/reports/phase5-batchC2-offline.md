# Phase 5 Batch C2 (part features): offline implementation report

Status: offline only, no SOLIDWORKS contact, no commits. Full suite `discover -s tests`: 473 tests OK (incl. compat test); smoke client lists 168 tools (this batch adds 7: `sheet_metal_base_flange`, `sheet_metal_edge_flange`, `sheet_metal_sketched_bend`, `sheet_metal_hem`, `sheet_metal_fold_unfold`, `export_flat_pattern`, `swept_thread`). New tests: 29 (sheet metal) + 24 (thread/hole/fillet).

## Items

| # | Tool / change | COM route (exact arg count asserted) | Success measured by |
|---|---|---|---|
| 2.1 | `sheet_metal_base_flange` | `IFeatureManager.InsertSheetMetalBaseFlange2`, 19 args, PCBA = `nothing()` | tree count grows; before/after volume + bbox returned |
| 2.2 | `sheet_metal_edge_flange` | `InsertSheetMetalEdgeFlange2`, 13 args, edge and sketch dispatch arrays | volume or bbox changed |
| 2.3 | `sheet_metal_sketched_bend` | `CreateDefinition(35)`, `BendAngle/PositionType/ReverseDirection/UseDefaultBendRadius/BendRadius/UseDefaultBendAllowance`, `SetFixedFace(x,y,z,nothing())`, `CreateFeature` | bbox or volume changed |
| 2.4 | `sheet_metal_hem` | `InsertSheetMetalHem2`, 16 args, selection driven | volume increased |
| 2.5 | `sheet_metal_fold_unfold` | `IModelDoc2.InsertSheetMetalUnfold/Fold` (0 args, via `value()`); flatten/unflatten = `EditUnsuppress2`/`EditSuppress2` on the `FlatPattern` feature | bbox changed |
| 2.6 | `export_flat_pattern` | `IPartDoc.ExportToDWG2`, 9 args; path via `validated_output_path` (.dxf only, under output_root, no overwrite unless asked) | file >0 bytes and contains `ENTITIES` |
| 2.7 | `swept_thread` | `create_helix` handler, `create_sketch`/`draw_line` x3/`close_sketch` for a 60 degree triangle, then `InsertCutSwept5` (22 args) or `InsertProtrusionSwept4` (20 args) with profile mark 1, helix mark 4 | volume delta has the right sign, body count unchanged, deviation from the analytic (Pappus) thread volume reported, `within_tolerance` at 3 % |
| 2.8 | `hole_wizard(cosmetic_thread=True)` | after each tapped hole, the circular opening edge is located (centre within 0.05 mm, radius within 25 % of the hole), then `InsertCosmeticThread3` 7 args, standard 2 (ISO), "Machine threads", size `M6x1.0`; read back through `GetDefinition().Size/Diameter` | CosmeticThread read-back matches, else `ok=false` |
| 2.8 | Value6 = 0 bug | Already fixed in the tree before this batch (`_hole_values` sets `values[5] = 1.0`); regression test added (HoleWizard5 arg 13 == 1.0) | n/a |
| 2.9 | `fillet_variant type=full_round` | `CreateDefinition(1)`, `data.Type = 3`, `SetFaces(3/4/5, dispatch_array)`, `CreateFeature`; any exception becomes the old refusal (`fenced=True`) with `FeatureFillet3` never called | volume decreased; faces before/after returned |

## Design notes
- `part_snapshot()` and `changed()` / `measured()` in `sw_sheetmetal.py` are the shared measurement helpers (`sw_thread` imports them).
- `sheet_metal_edge_flange` takes `profile_sketches` (one per edge) instead of `length`: the 2017 member has no length argument; the plan's `length` is the sketch.
- `k_factor` (plan 2.1) is not exposed: `InsertSheetMetalBaseFlange2` only takes an `ICustomBendAllowance` (PCBA); we pass `nothing()` (part default allowance). A later `edit_feature`/`ISheetMetalFeatureData.KFactor` route can set it.
- `swept_thread` assumes the cylinder axis passes through the profile-sketch origin along sketch axis `axis`; `start_mm` is the helix start in the profile plane's sketch coordinates. The plan's `cyl_face/edge` input is replaced by explicit `circle_sketch` + `profile_plane`, because a face cannot tell us the plane that holds the axis and the helix start.
- Plan 2.9 live check says "face count drops"; for a full round the centre face is replaced by one cylinder face, so the count is likely unchanged. The tool therefore gates on volume and returns face counts; the live script checks for a cylinder face and the analytic removed volume.

## LIVE-PROBE constants (most likely value, to be confirmed live)
`sw_sheetmetal.py`: `SM_BASE_FLANGE_DIR_TO_USE=1`; `SM_FLANGE_SHARP_TYPE=0`; `SM_HEM_TEAR_RIP=1` (only read when custom relief); `SM_MARK_FIXED_FACE=1`, `SM_MARK_BENDS=2` (unfold/fold marks; live script retries 0/0); `SB_MARK_SKETCH=0` (sketched-bend sketch mark; retries 1); sketched-bend `PositionType` reuses `FLANGE_POSITIONS` (swFlangePositionTypes_e); `EXPORT_SM_GEOMETRY=1`, `EXPORT_SM_BEND_LINES=4`, `EXPORT_SM_SKETCHES=8` (ExportToDWG2 SheetMetalOptions bits, not in swconst); `Alignment`/`Views` passed as empty variants; relief block args use "rectangular, ratio 0.5" with `UseDefaultRelief=True`; edge-flange `FlangeSharpType`. `sw_thread.py`: `THREAD_TWIST_CONTROL=0`, helix/profile marks 1 and 4 (same as `sweep`), profile triangle geometry (30 degree half angle, depth 0.6134 x pitch, 10 % overshoot). Edge-flange profile direction and Right-plane sketch axis sign are probed both ways in the live script.

## Requests for shared files (orchestrator only)
- `docs/FORK_CHANGES.md`: add under `sw_feature.py`: "hole_wizard: new `cosmetic_thread` flag (ISO cosmetic thread on each tapped hole via InsertCosmeticThread3, helpers `_metric_thread`, `_hole_opening_edge`, `_add_hole_cosmetic_thread`); fillet_variant: `full_round` now builds through CreateDefinition(swFmFillet)+ISimpleFilletFeatureData2 (`_full_round_fillet`, `_volume_mm3`), falling back to the previous refusal; new imports `re`, `Sequence`, `dispatch_array`, `byref_long`, `enumerate_edges`, `iter_face_objects`; constants `FM_FILLET`, `HOLE_COSMETIC_*`, `HOLE_EDGE_*`." Also list new fork-owned modules' tool additions (7 tools above).
- `sw2017_fences.py`: nothing now. Candidates after the live pass: whichever of 2.2, 2.3, 2.5, 2.9 fails twice (the live script prints FENCE-CANDIDATE). Note `fillet_variant full_round` is still refused in-tool (not in FENCES) when the new route fails.
- `server.py` / `sw_core.py`: no change needed.
- `tests/test_sw2017_batchB_geometry.py::test_full_round_refused_on_2017` still passes (route exceptions on the fake doc return the `fenced=True` refusal); rename it if the orchestrator wants the name to reflect the new behavior.
- Unrelated: `test_sw2017_batchC_assembly.CreateSubassemblyTests.test_virtual_mode_default` failed once mid-run while another agent was editing; it passed in the final full run.

## Live script
`tests/live_p5_batchC2.py` (not run). Stages: `sm_base sm_edge sm_bend sm_hem sm_fold sm_export thread hole fillet`; fixtures built in-script; output `sandbox/phase5/batchC2/`; prints PASS / FAIL / FENCE-CANDIDATE (second failed attempt of an item).
