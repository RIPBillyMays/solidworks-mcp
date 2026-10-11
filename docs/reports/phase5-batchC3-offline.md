# Phase 5 Batch C3: offline implementation report

Scope: plan items 3.1-3.12. Offline only; nothing was run against SOLIDWORKS. Full suite: 473 tests OK (incl. compat and enum tests); smoke client lists 168 tools (other sub-batches contribute to that number).

## Tools added

| Tool | Module | COM route (exact arg counts) | Success measure |
|---|---|---|---|
| `surface_extrude` | sw_surface | `IFeatureManager.FeatureExtruRefSurface3` (22, void) | surface-body count +1 |
| `surface_revolve` | sw_surface | `InsertRevolvedRefSurface` (4) | surface-body +1 |
| `surface_loft` | sw_surface | `IModelDoc2.InsertLoftRefSurface2` (6, void) | surface-body +1 |
| `surface_offset` | sw_surface | `IModelDoc2.InsertOffsetSurface` (2, void) | surface-body +1 |
| `surface_knit` | sw_surface | `InsertSewRefSurface` (5) | surface count drops; with `try_form_solid`, a new solid with volume > 0 |
| `thicken` | sw_surface | `FeatureBossThicken` (7, returns feature) | volume grows; without merge exactly +1 solid |
| `surface_trim` | sw_surface | `PreTrimSurface` (4) then `PostTrimSurface` (1) | surface area or body count changed (else "silent no-op") |
| `replace_face` | sw_surface | `IModelDoc2.InsertFeatureReplaceFace` (0, void) | volume or bbox changed |
| `edit_feature` | sw_edit | `GetDefinition` / `feature_data` / `ModifyDefinition` | read-back from a fresh definition after rebuild |
| `split_body method="cut"` | sw_edit.`split_via_cut`, dispatched from sw_body | `FeatureCut4` (27) via `call_versioned` (Cut3 fallback), two directions, through-all both | solid count rises, no rebuild errors |

Every surface result carries `before`/`after` snapshots (feature count, surface and solid body counts and names, surface area, volume, bbox) and `verified`. A returned feature with a failed expectation gives `ok=false` and "NOT VERIFIED: ...". Bad arguments are rejected before `require_part()`.

Surface bodies are invisible to `list_faces`/`list_bodies`, so inputs are `selection` (normal spec), `surface_faces` (index across all sheet-body faces) or `surface_bodies` (names, reported in every result).

`edit_feature` allow-list (ADR-0007/D5), keyed by `GetTypeName2`: Extrusion (depth_mm, reverse), Fillet (radius_mm), Chamfer (distance_mm), LPattern (spacing_mm, count), CirPattern (count, angle_deg), Shell (thickness_mm). Anything else is refused with the type named. Per param: `changed` / `unchanged` (already held, ModifyDefinition skipped) / `failed` (accepted but read-back differs). Top-level `changed` is true only if a read-back differs from before and equals the request.

Decisions kept: 3.10 `combine_bodies` stays fenced (no route); 3.12 `set_mass_override` stays fenced (D4), `sw_docdata.py` untouched.

## 3.11 caveat (differs from the plan's "volume unchanged")
A FeatureCut4 cannot split without removing the cutting profile's prism, so total volume drops by the kerf. The tool reports `kerf_volume_mm3`; it needs a closed profile sketch spanning the body. Unknown: whether 2017 keeps all resulting bodies without the multi-body prompt. Entry point is `split_body(method="cut")` (schema gained `method`); the fence entry is untouched, so the live pass uses `SW_MCP_DISABLE_FENCES=1` (the live script calls the function directly, which bypasses the fence anyway).

## LIVE-PROBE constants (unverified on 2017)
sw_surface: `REVOLVE_MARK_AXIS=4`, `LOFT_MARK_PROFILE=1`, `LOFT_TESS_TOLERANCE=1.0`, `LOFT_MATCH_NONE=0`, `SURFACE_BODY_TYPE="SURFACEBODY"` (SelectByID2 type), `KNIT_TOLERANCE_M=0.0001` / `KNIT_MAX_GAP_RANGE_M=0`, `THICKEN_SIDES={side1:0, side2:1, both:2}` (and whether "both" is total or per-side), `THICKEN_FACE_INDEX=0`, `TRIM_MARK_TOOL=1` / `TRIM_MARK_PIECES=2`, `REPLACE_MARK_TARGET=1` / `REPLACE_MARK_SURFACE=2`.
sw_edit: the six `GetTypeName2` strings ("Extrusion", "Fillet", "Chamfer", "LPattern", "CirPattern", "Shell"); `CHAMFER_SIDE_1=0`; fillet via `DefaultRadius` (since `SetRadius` needs a fillet-item object; untested on multi-radius fillets); `EXTRUDE_DIRECTION_1=True`; whether a fresh `GetDefinition()` without `AccessSelections` reads valid values; whether Extrusion also matches cut-extrudes (type "Cut": deliberately NOT allow-listed, propose adding after a round-trip).
Verified against the enum dump: `START_SKETCH_PLANE`, revolve types, end conditions.

## Shared-file requests (orchestrator-only files)
- `sw2017_fences.py`: none now. After the live pass, add fences with attempt evidence for whichever of `surface_trim` / `replace_face` / `surface_knit` (form solid) / `split_body` cut route come back FENCE-CANDIDATE. `split_body` entry reason should mention the cut route if it fails too.
- `server.py`: none (modules already imported).
- `docs/FORK_CHANGES.md` lines:
  - `solidworks_mcp/sw_body.py`: `split_body` gains `method` ("split" default, "cut"); "cut" routes to `sw_edit.split_via_cut` (FeatureCut4 through-all kerf split, 2017 retry for the PostSplitBody no-op). Marked `# Modified for SOLIDWORKS 2017 support (fork).` at the dispatch.
  - New: `sw_surface.py` (8 surface tools), `sw_edit.py` (`edit_feature`, `split_via_cut`), tests `test_sw2017_batchC_surface.py` (33), `test_sw2017_batchC_edit.py` (28 incl. dispatch), live `live_p5_batchC3.py`.
- Tool count: +9 registered tools from C3 (8 surface + `edit_feature`).

## Live pass notes
Run order in `tests/live_p5_batchC3.py`: `surf knit thicken trim replace edit split`. Stages print PASS / FAIL / FENCE-CANDIDATE. Trim uses 2 attempts (keep one side, then remove the other) before saying FENCE-CANDIDATE. The circular-pattern edit check assumes an axis named "Y"; adjust if the selection helper wants another name.
