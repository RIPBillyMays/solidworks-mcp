# Phase 5 Batch C3 live pass (2026-10-11)

SW 2017 live, in-process via `tests/live_p5_batchC3.py` (stages run item by item). No modal dialogs hit. Probe docs closed; open-doc list empty. Unit tests: 478 OK.

| # | Tool | Result | Reason / evidence |
|---|---|---|---|
| 3.1 | surface_extrude | PASS | circle r10 x20: area 1256.64 = 2*pi*r*L; mid_plane+caps -> 1 solid V=6283.19 = pi r^2 L; depth<=0 refused |
| 3.2 | surface_revolve | PASS | 360 deg area 1256.64; 90 deg 314.16 (quarter) |
| 3.3 | surface_loft | PASS | r10->r5 over 20: area 971.48 = analytic frustum |
| 3.4 | surface_offset | PASS | by 2: +1 surface, area 1507.96 (outward); distance 0 copies (n=3) |
| 3.5 | surface_knit | PASS | 2 planar surfaces -> 1, area 350 preserved; try_form_solid: 0 -> 1 solid, V=4000 |
| 3.6 | thicken | PASS | side1 dV=400 (20x10x2); side2 400; both = 800 (thickness is PER SIDE for "both") |
| 3.7 | surface_trim | FENCE-RECOMMENDED | `PreTrimSurface` returns True, `PostTrimSurface` returns None in every variant: 8 mark combos (1,2)(2,4)(0,0)(1,1) x keep/remove (c3f), 5 Mutual/Keep/Sew arg variants (c3g), plus the tool's 2 attempts. Surface count 2 and area 300.0 unchanged |
| 3.8 | replace_face | PASS | top face of 20x20x10 block replaced by surface 2 mm up: V 4000 -> 4800 (dV 800), bbox z 10 -> 12 |
| 3.9 | edit_feature | FIXED | Root cause: `IFeature.GetDefinition` is PROPGET on 2017, calling it raised "Member not found" (all types failed). Now read via `value()`. Then PASS: Extrusion depth 10->25 (bbox z 25), same value -> changed=false, reverse (min z 0 -> -25); Fillet r1->3 (V 1997.85->1980.69); Chamfer 1->2.5 (1995->1968.75); Shell 1->2 (1084->1952); LPattern count 3->4 spacing 10->12 (+62.83 = one 5 mm pin); CirPattern count 3->5 (+125.7); sketch refused, lists supported types |
| 3.11 | split_body method=cut | PASS | 2 solid bodies, V 8000 -> 7600 (loss 400 = kerf exactly); unknown method refused |
| bonus | swept_thread mode=boss (external) | PASS | M10x1.5 bolt r5, length 9: +97.925 mm3 vs analytic 97.783 (0.14 %), 1 body, within_tolerance. Probe `sandbox/probe/c3j.py` |

## Probed constants (all worked as set)
`REVOLVE_MARK_AXIS=4`, `LOFT_MARK_PROFILE=1`, knit tolerance 0.0001 m, `THICKEN_SIDES` side1=0/side2=1/both=2 (both = t on each side), `REPLACE_MARK_TARGET=1/REPLACE_MARK_SURFACE=2`, `EXTRUDE_DIRECTION_1=True`, `CHAMFER_SIDE_1=0`, fillet `DefaultRadius` (single-radius fillet OK). GetTypeName2 strings confirmed: Extrusion, Fillet, Chamfer, LPattern, CirPattern, Shell (sketch = ProfileFeature). A fresh `GetDefinition` with `AccessSelections` reads valid values. Trim marks (tool 1/pieces 2) did not matter: PostTrim is None regardless.

## Files changed
- `solidworks_mcp/sw_core.py`: `feature_data` reads `GetDefinition` via `value()` (shared helper, ADR-0007; offline tests still pass).
- `solidworks_mcp/sw_edit.py`: read-back uses `value(fresh, "GetDefinition")`.
- `solidworks_mcp/sw_surface.py`, `tests/test_sw2017_batchC_surface.py`: previous agent's edits, unit-consistent, not re-edited.
- `tests/live_p5_batchC3.py`: 3.9d expects "ProfileFeature"; pattern fixtures fixed (proud pin at y=15, +X edge as direction, hub cylinder face as circular axis).

## Fence recommendations (orchestrator applies; fences.py untouched)
- `surface_trim`: PostTrimSurface returns None on 2017 (evidence above). Not fenced inside the handler; it currently refuses cleanly with before/after snapshot.
- FORK_CHANGES: note the `feature_data` GetDefinition fix. `thicken` with a missing body raises RuntimeError (server wraps) rather than returning ok=False; acceptable.
