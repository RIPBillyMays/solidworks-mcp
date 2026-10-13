# Phase 5 Batch C2 live pass (2026-10-11)

SW 2017 live, in-process via `tests/live_p5_batchC2.py` (output under `sandbox/phase5/batchC2/`). No modal dialogs hit. Leftover probe docs (Part12..) were closed with force; final open-doc list is empty. Unit tests: 479 OK.

| # | Tool | Result | Reason / evidence |
|---|---|---|---|
| 2.1 | sheet_metal_base_flange | FIXED | `Merge/UseFeatScope/UseAutoSelect = True` made `InsertSheetMetalBaseFlange2` return None; all-False works (Merge=True is the culprit). Tree has Sheet-Metal1/BaseFlange/Flat-Pattern1; volume 10000.0 = 100x50x2; open L profile bbox 42x32x50 |
| 2.2 | sheet_metal_edge_flange | PASS (probe order) | First sketch direction (+x on Right plane) fails (None); second (-x) builds, bbox z 2 -> 20, 1 body. Live test also had a wrong edge predicate (picked the 2 mm edge); fixed in the test |
| 2.3 | sheet_metal_sketched_bend | FENCE-RECOMMENDED | `CreateDefinition(35)` returns None on a sheet-metal part with or without sketch/face selected. `CreateDefinition(34)` works, 0-6,36-41 return None. No Insert member in 2017. Edit route impossible without an existing feature |
| 2.4 | sheet_metal_hem | PASS (test fix) | Test selected the wrong edge. Closed hem inside on the long edge: volume +1439.7 (expected ~1600, in 0.8-2.5x window) |
| 2.5 | sheet_metal_fold_unfold | PASS (test fix) | unfold: bbox [42,32,50] -> [70.71,2,50]; fold needs the flat bend strip (smallest -y plane) not a cylinder; fold restores [42,32,50]; flatten/unflatten OK |
| 2.6 | export_flat_pattern | PASS | flat.dxf 22793 bytes, has ENTITIES, outline 50 x 70.712 matches flat bbox; outside-root path refused |
| 2.7 | swept_thread | FIXED | Cut with 10 % base overshoot removed a constant +5.1 % too much on a bolt (independent of radius/length); overshoot 0 for cuts: external 86.34 vs 86.48 (-0.16 %), internal 79.32 vs 79.36 (-0.05 %), 1 body, check_errors clean. Boss keeps overshoot (needed to fuse; boss not tested live) |
| 2.8 | hole_wizard cosmetic_thread | FIXED | Size must be `M6x1.0` (test used `M6x1`: wizard returns None). Wizard centres the hole ~0.08 mm off the picked point, so `HOLE_EDGE_CENTER_TOL_MM` 0.05 -> 0.5. Result: removed 352.0 mm3; CosmeticThread sub-feature present, readback `M6x1.0`, d 6.0 |
| 2.9 | fillet_variant full_round | FENCE-RECOMMENDED | `CreateDefinition(1)` returns None (all types except 34). Alternative: GetDefinition of a plain fillet then `Type=3` fails, `Type` is read-only. FeatureFillet3 route already exhausted in Batch B. Tool refuses with `fenced=True`; volume unchanged (0.0 removed) |

## Probed LIVE-PROBE constants
`SM_BASE_FLANGE_DIR_TO_USE=1` works (0 also). `SM_RELIEF_RECTANGULAR=1`, `SM_END_BLIND=0` fine. `SM_MARK_FIXED_FACE=1, SM_MARK_BENDS=2` work for unfold/fold. Hem: `HEM_TYPES closed=1`, position inside=0 OK, `SM_HEM_TEAR_RIP=1` OK. Edge flange: `EDGE_OPT_DEFAULT_RELIEF` options, `SM_FLANGE_SHARP_TYPE=0`, sketch direction -x (Right plane) is the one that works for a sheet at z -2..0. Export `ExportToDWG2` options 1/4/8 accepted. `SB_MARK_SKETCH` irrelevant (fenced). Thread marks 1/4 and `THREAD_TWIST_CONTROL=0` OK.

## Files changed
- `solidworks_mcp/sw_sheetmetal.py`: base flange Merge/FeatScope/AutoSelect -> False.
- `solidworks_mcp/sw_thread.py`: no overshoot for cuts.
- `solidworks_mcp/sw_feature.py`: `HOLE_EDGE_CENTER_TOL_MM=0.5`; explicit None check on `CreateDefinition(swFmFillet)` (clearer fenced message).
- `tests/test_sw2017_batchC_sheetmetal.py`, `tests/test_sw2017_batchC_thread.py`: updated for the above.
- `tests/live_p5_batchC2.py`: long-edge predicate, fold bend-face selection, `M6x1.0`, cosmetic thread read as sub-feature, backslash warning.
- FORK_CHANGES should note the hole tolerance and fillet None check (orchestrator).

## Fence recommendations (orchestrator applies)
`sheet_metal_sketched_bend` (CreateDefinition(35) None on 2017), `fillet_variant type=full_round` (already refuses; add to FENCES so it is listed). Also: hole_wizard docs should say size strings must be exact (`M6x1.0`).
