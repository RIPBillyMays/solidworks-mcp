# Phase 4 offline implementation report

Offline only; no SOLIDWORKS touched. Tests: 97 OK (74 before, +23 in `tests/test_sw2017_phase4.py`). `mcp_smoke_client.py`: 92 tools; `auto_dimension_view` description starts "NOT SUPPORTED ON SOLIDWORKS 2017". Static compat test passes.

## Changes
1. **Fences (ADR-0006):** new `solidworks_mcp/sw2017_fences.py` (`FENCES`, `apply_fences`; KeyError on unknown name; `SW_MCP_DISABLE_FENCES=1` skips; idempotent). Hook in `server.py` after module imports. Fenced handler returns `ok False`, `data.fenced True`, no COM.
2. **chamfer:** `equal_distance` -> `angle_distance` 45 deg, same distance; `data.substituted = "angle_distance 45°"`; description + message updated. A stray `angle_deg` is ignored in this mode.
3. **rib:** up to 4 attempts over (normal_to_sketch, reverse_material) combos, requested first; result data reports `extrude_direction`, `reverse_material`, `retried`. `_feature_created_after` measurement unchanged.
4. **insert_component:** after AddComponent5, read transform, build corrected 16-double matrix (translation = x/y/z in metres) and apply with `app.GetMathUtility().CreateTransform` + `component.SetTransformAndSolve2`. All members confirmed in `sw2017_api_members.txt`. Failure to move yields `data.warning`; result always reports `origin_mm`.
5. **export_document:** success = errors == 0 and non-empty file written by this call (new, or changed when overwriting). Codes returned as `data.errors`/`data.warnings`. Also applies to `save_document` via shared `_save_as` (same criteria; ordinary saves unaffected).
6. **Smoke script:** cleanup tracks documents that appeared during suite steps (plus `X["docs"]`) and closes only those, never baseline or foreign docs; 9.1 also restricted. `Fenced` exception -> `FENCED` status (counts as good). Section depth check: NOT strengthened; left a TODO (no known 2017 property exposing partial depth without live probing); stays UNVERIFIED.

## Needs live verification in T4
- chamfer default now changes volume by -40 mm3 on the Phase 3 test cube.
- rib corner-gusset case builds with default args (+800 mm3).
- insert_component at (0,0,0) reads origin_mm [0,0,0]; at (100,0,20) reads [100,0,20]. SetTransformAndSolve2 on a fixed (first) component may not move it: check; `data.warning` will say so. Mate solver may still shift under-constrained parts.
- export .3mf returns ok with warnings code in data.
- Cleanup leaves no foreign docs closed; auto_dimension_view case reports FENCED.
