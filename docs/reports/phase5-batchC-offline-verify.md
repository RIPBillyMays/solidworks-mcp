# Phase 5 Batch C: offline verification (C1 + C2 + C3)

Verifier: separate Sonnet agent; read-only except this file. No SOLIDWORKS contact, no commits.

## Results
- `.venv\Scripts\python.exe -m unittest discover -s tests`: **Ran 474 tests, OK**.
- `tools\compat\mcp_smoke_client.py`: **tool count 168** (146 + 6 C1 + 7 C2 + 9 C3). Expected 168: match.
- Fences: `solidworks_mcp/sw2017_fences.py` unchanged (not in `git status`). `combine_bodies`, `split_body`, `set_mass_override` still in FENCES (lines 38/44/49). `split_body method="cut"` is only reachable with fences disabled (fence wraps the whole tool; test `test_split_body_stays_fenced`). `sw_docdata.py` untouched.
- Scope: modified upstream files are `server.py`, `sw_core.py` (C0 only: 6 imports, `register_flag_methods`, `feature_data`), `sw_assembly.py`, `sw_body.py`, `sw_feature.py` (all within ownership). `docs/FORK_CHANGES.md` has only the C0 lines; C1-C3 entries are still pending the orchestrator.
- COM members: every member called by the new modules is in `sw2017_api_members.txt` and on the right interface (checked by hand, including `IFeatureManager.InsertDerivedPattern2`, `IModelDoc2.InsertSheetMetalUnfold/Fold`, `IPartDoc.ExportToDWG2`, `IFeatureManager.PreTrimSurface/PostTrimSurface/FeatureBossThicken/InsertSewRefSurface/InsertRevolvedRefSurface`, `IModelDoc2.InsertLoftRefSurface2/InsertOffsetSurface/InsertFeatureReplaceFace`, `IAssemblyDoc.MirrorComponents3/InsertNewVirtualAssembly/MakeAssemblyFromSelectedComponents`). Positional counts re-counted against the typelib probe and all match: AddMate5 15, InsertMateReference2 12, FeatureLinearPattern5 22, FeatureCircularPattern5 14, MirrorComponents3 14, BaseFlange2 19, EdgeFlange2 13, Hem2 16, ExportToDWG2 9, InsertCutSwept5 22, InsertProtrusionSwept4 20, FeatureExtruRefSurface3 22, InsertSewRefSurface 5, FeatureBossThicken 7, PreTrimSurface 4, InsertCosmeticThread3 7.
- Enums (item 6): every numeric value in the `dict(...)` tables and `Final` constants was cross-checked against `sw2017_enums.txt`: mate types (gear 10, rack 13, screw 17, cam 9, hinge 22, path 15, limit 5/6), width options 0-3, mate reference types/alignments, mirror orientation/name modifier, relief 1, end cond 0, flange positions 1-6, edge-flange option bits 1/2/4/8/128, hem types/positions, `swFmSketchBend` 35, `swFmFillet` 1, full-round 3, DWG action 1, revolve types 0/2, thicken sides 0/1/2, start plane 0. **All match.** Not enum-backed and flagged LIVE-PROBE (marks, `SM_BASE_FLANGE_DIR_TO_USE`, `SM_FLANGE_SHARP_TYPE`, export option bits, `THREAD_TWIST_CONTROL`, fillet face-set marks 3/4/5) are guesses by design.

## Findings, ranked

### Blocking
None.

### Medium
1. `solidworks_mcp/sw_assembly.py:~621-636`: `doc.AddMate5(*mate_args)` is **not inside `dialogs_suppressed()`** (global rule 2). Batch A plain mates had the same shape, but the new hinge/path/cam/slot/gear paths are the ones most likely to open a mate PropertyManager or a modal. Wrap the call (plan branch at least).
2. `sw_assembly.py:~651-668` (advanced mate success): success is gated on the **built `IMate2.Type` only**. If `safe(mate, "Type")` returns None (unreadable) the tool returns ok with `built_type=None`, and it never requires `mate_count_after > mate_count_before` or a new tree entry (it only reports them). Rule 3 wants the measured delta to decide. Suggest: fail when `created` is empty / mate count did not grow.
3. `sw_feature.py` `_add_hole_cosmetic_thread` (new, near the `InsertCosmeticThread3` call): if `GetDefinition()` returns None the entry stays `ok: True` with no read-back, i.e. success on a COM return value. Should be `ok: False` ("could not verify").
4. Live scripts `tests/live_p5_batchC2.py` and `live_p5_batchC3.py` rely on `SW_MCP_OUTPUT_ROOT` being set to the sandbox but never assert it. `sw_core.py:139` defaults the output root to `~/Documents/solidworks-mcp`, so if the env var is forgotten, `save_document({"path": "phase5/batchC2/..."})` (C2:305) and the DXF export (C2:312) write **outside `sandbox/`**. C1 uses absolute sandbox paths (fails closed) but also lacks the guard. Add `assert OUTPUT_ROOT == ROOT/"sandbox"` at start of all three.

### Low
5. `sw_sheetmetal.py` `sheet_metal_base_flange` (~213-224): expectation is tree-count growth only (`measured(..., "tree")`); the plan's volume = area x t check is only in the live script. A base flange that returns a feature with zero volume would pass. Suggest `"volume_up"` or `"geometry"`.
6. `sw_body.py` and `sw_assembly.py`/`sw_feature.py`: fork comment present (`sw_assembly.py:14`, `sw_feature.py:14`); `sw_body.py` only has the inline comment at line 260, no header line under the Apache block. Add the standard `# Modified for SOLIDWORKS 2017 support (fork).` header.
7. `sw_surface.py` `_select_inputs` raises `RuntimeError` out of the tool body in knit/thicken/trim/replace/offset (not converted to `result(False, ...)`). It still happens before any create, so no harm, but the selection set is left populated; wrap with `try/except` + `clear_selection`.
8. `sw_asm_pattern.py` `pattern_driven_component_pattern`: `expected_new_components` is optional; without it any >= 1 new component passes, so it does not enforce plan 1.13 "count = driving instance count". Consider deriving the expected count from the driving pattern.
9. `sw_mates_adv.py` `add_mate_reference`: success = a new MateReference feature; the plan's ">= 1 entity" is not measured (no read-back of the reference entities). Out-of-range message prints `0..-1` when a pool is empty.
10. `sw_feature.py` `_full_round_fillet`: when CreateFeature returns a feature but the volume did not drop, the tool returns ok False but leaves the useless feature in the tree (no cleanup). Same pattern in several surface/sheet-metal paths (they report "silent no-op" and leave the feature); acceptable offline, decide at live pass whether to delete.
11. `hem`: `gap_mm`, `radius_mm`, `miter_gap_mm` are not validated for sign before COM (`sw_sheetmetal.py` ~366-390).
12. Live scripts close any doc not present at start (`finish()` in all three), which would also close a doc Zach opens mid-run. Acceptable under ADR-0005 if he stays hands-off; stated for completeness. Output dirs are `sandbox/phase5/batchC1|C2|C3/` (plan says `batchC/`; still under `batchC*`).
13. `docs/FORK_CHANGES.md` still lacks the C1/C2/C3 lines requested in the three implementer reports (orchestrator-owned).

## Per-tool table

| tool | item # | verdict | note |
|---|---|---|---|
| add_mate limit_distance/limit_angle | 1.1 | ISSUE | validated pre-COM, counts OK; but AddMate5 not in `dialogs_suppressed` (#1), no mate-count gate (#2) |
| add_mate gear | 1.2 | ISSUE | same #1/#2; ratio args 7-8 OK |
| add_mate rack_pinion | 1.3 | ISSUE | same #1/#2; value slot is a LIVE-PROBE |
| add_mate screw | 1.4 | ISSUE | same #1/#2 |
| add_mate cam | 1.5 | ISSUE | same #1/#2; marks LIVE-PROBE |
| add_mate hinge | 1.6 | ISSUE | same #1/#2; min entities 4 enforced pre-AddMate5 |
| add_mate slot | 1.7 | ISSUE | same #1/#2 |
| add_mate path | 1.8 | ISSUE | same #1/#2; likely fence |
| add_mate symmetric/width | 1.9 | ISSUE | same #1/#2 |
| add_mate_reference | 1.10 | OK | InsertMateReference2 12 args in dialogs_suppressed; success needs new MateReference (minor #9) |
| linear_component_pattern | 1.11 | OK | FLP5 22 args, suppressed, success = components x (count-1) new components + tree growth |
| circular_component_pattern | 1.12 | OK | FCP5 14 args, same verdict |
| pattern_driven_component_pattern | 1.13 | OK | right owner (IFeatureManager, 0 args); expected count optional (#8) |
| mirror_components | 1.14 | OK | 14 args, suppressed, requires one new component per source |
| create_subassembly | 1.15 | OK | virtual default, children + top-level delta measured; file mode path confined to output root |
| sheet_metal_base_flange | 2.1 | OK (minor #5) | 19 args, suppressed; tree-only expectation |
| sheet_metal_edge_flange | 2.2 | OK | 13 args, inputs validated first, volume/bbox delta |
| sheet_metal_sketched_bend | 2.3 | OK | CreateDefinition(35) inside suppression, bbox/volume delta |
| sheet_metal_hem | 2.4 | OK (minor #11) | 16 args, volume must grow |
| sheet_metal_fold_unfold | 2.5 | OK | uses IModelDoc2 via `value()`, flatten via EditSuppress2; bbox delta decides (`ok=True` is overridden by `moved`) |
| export_flat_pattern | 2.6 | OK | validated path, 9 args, file size + ENTITIES decide |
| swept_thread | 2.7 | OK | InsertCutSwept5 22 / Protrusion4 20 args; volume sign, body count, Pappus deviation, check via feature_result |
| hole_wizard cosmetic_thread | 2.8 | ISSUE | #3 (no read-back when GetDefinition is None) |
| fillet_variant full_round | 2.9 | OK (minor #10) | volume must drop, any exception returns the old refusal |
| surface_extrude | 3.1 | OK | 22 args, void return handled by tree diff, exactly +1 surface body |
| surface_revolve | 3.2 | OK | InsertRevolvedRefSurface 4 args |
| surface_loft | 3.3 | OK | doc-level InsertLoftRefSurface2 6 args |
| surface_offset | 3.4 | OK (minor #7) | InsertOffsetSurface 2 args |
| surface_knit | 3.5 | OK | solid + volume > 0 required when requested |
| thicken | 3.6 | OK | FeatureBossThicken (returns feature), volume growth + solid +1 |
| surface_trim | 3.7 | OK | Pre/Post pair; area/body delta required; refuses on Pre false |
| replace_face | 3.8 | OK | volume or bbox delta |
| edit_feature | 3.9 | OK | uses `sw_core.feature_data` (releases access in finally), exactly 6 types allow-listed in `EDIT_TYPES`, no-change detected by read-back (`unchanged` skips ModifyDefinition), fresh definition re-read after rebuild, errors via whats_wrong |
| combine_bodies | 3.10 | OK | untouched, still fenced |
| split_body method=cut | 3.11 | OK | FeatureCut4 (Cut3 fallback), solid count must rise, rebuild errors fail it; still behind the fence |
| set_mass_override | 3.12 | OK | untouched, still fenced |

Counts: **OK 26 (incl. 4 with minor notes), ISSUE 10** (nine add_mate rows share two root causes, #1 and #2; plus #3).

## Live script check (item 8)
- Writes: C1 under `sandbox/phase5/batchC1/` (parts, `.SLDASM`, log) via absolute paths; C2/C3 relative to the output root (needs the guard in #4). None opens a non-sandbox file; no `ExitApp`; each closes only documents not open at start (`finish()`), and C1 also asserts "final docs == baseline".
- Measurement: gear ratio, rack/screw travel, limit drag, pattern gaps, mirror x = -x, thread analytic volume, DXF contents, surface areas, thicken volume, edit read-backs all follow the plan's Live verification column. No stage for 3.12 (kept fenced).

## Fixes applied
1. add_mate: `AddMate5` now inside `dialogs_suppressed()` (sw_assembly.py; imported from sw_core). Test: `test_addmate5_runs_inside_dialogs_suppressed`.
2. Advanced mates: fail when mate count did not grow; wrong built type still fails; unreadable type + growth returns ok with `type_unverified: true`. Tests: `test_no_mate_count_growth_is_a_failure`, `test_unreadable_type_with_growth_is_ok_but_unverified`; `_run` fixture now grows the tree.
3. hole_wizard cosmetic thread: `GetDefinition()` None gives entry ok False, `cosmetic_thread_verified: false` and a warning; the hole stays ok. Explicit size mismatch still fails the call. Test: `test_unreadable_definition_is_unverified_not_ok`.
4. live_p5_batchC1/C2/C3.py abort at import unless `OUTPUT_ROOT == <repo>\sandbox` (batch B has no guard; not changed).
5. Base flange: also requires volume > 0 and exactly 1 solid body when readable; reports `solid_bodies`. Test: `test_zero_volume_or_wrong_body_count_is_a_failure`.
6. sw_body.py: fork header line added.
7. (item 13) FORK_CHANGES.md: C1/C2/C3 rows added.
11. hem: runtime sign validation for length/radius/gap/miter_gap before COM.
Not changed (Low, decide at live pass): #7, #8, #9, #10, #12.
Result: 479 tests OK; smoke client 168 tools.
