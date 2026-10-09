# Phase 4 offline verification

Overall: PASS (no blocking defects; 2 low-severity notes). Offline only, no COM touched.

1. Unit tests: PASS. `unittest discover -s tests`: Ran 97, OK.
2. Smoke client: PASS. 92 tools; `auto_dimension_view` description starts "NOT SUPPORTED ON SOLIDWORKS 2017: IDrawingDoc.AutoDimension ...".
3. Fencing: PASS. Registry `FENCES` + `apply_fences` in `solidworks_mcp/sw2017_fences.py`; one-line hook at `solidworks_mcp/server.py:65` runs at import after all module imports. Root `server.py` imports `solidworks_mcp.server`, and the console script is `solidworks_mcp.server:run`, so both paths run it. Tool stays listed. Handler returned `{'ok': False, ..., 'data': {'fenced': True}}` with no COM. KeyError on unknown name and the env bypass both have tests.
4. chamfer: PASS. equal_distance becomes angle_distance with 45 and the same distance. `to_rad(angle_deg)` is the same radians path as the existing angle_distance code. Description and `data.substituted` document it.
5. rib: PASS. 4 combos, requested first, break on first success. Result reports `extrude_direction`, `reverse_material`, `retried`. `_feature_created_after` verification kept; the sketch is re-selected on each attempt.
6. insert_component: PASS. `corrective_matrix` keeps rotation and scale and replaces only the translation (slots 9-11, metres, mm converted with `to_m`). It composes with the existing transform and does not overwrite it. `apply_transform` uses the same layout. Members in `sw2017_api_members.txt`: ISldWorks.GetMathUtility, IMathUtility.CreateTransform, IComponent2.SetTransformAndSolve2, IAssemblyDoc.AddComponent5; objects match (`app`, math utility, `component`). Failure gives `data.warning`. Live-only risk: a fixed first component may not move.
7. export/save: PASS. `_save_as` takes a before-stamp (mtime_ns, size). Success needs errors==0, size>0, and (returned True or the stamp changed). A stale pre-existing file with return False does not count, so `save_document` is safe.
8. Smoke script: PASS. Cleanup is restricted to `_own_titles()` (titles that appeared during steps, plus `X["docs"]`) and never baseline. The Fenced exception maps to FENCED, which is in GOOD. Section-view TODO present.
9. Headers/log/scope: PASS. The fork header is present on server.py, sw_assembly.py, sw_feature.py and sw_file.py. Four log rows plus the server row in FORK_CHANGES. Changes are within scope; no Phase-2 carry-over fixes seen.

Defects
- Low: `solidworks_mcp/sw_file.py` ~L100: when exporting to the document's own path, the Save3 early return skips `report`, so `data.errors`/`warnings` are absent.
- Low: `tests/live_sw2017_smoke.py` `_open_titles`: returns an empty set if the query fails. A transient failure before a step would mark all documents opened as suite-owned (baseline still excluded).
- Nit: `docs/adr/README.md` has a stray double blank line.

## Orchestrator follow-up (2026-10-08)
- Defect 1 fixed: `sw_file._save_as` now fills `report` (errors/warnings) on the own-path `Save3` branch too.
- Defect 2 fixed: `_open_titles()` returns `None` on a failed query, and ownership is recorded only when both before/after queries succeed.
- Defect 3 fixed: trailing blank lines removed from `docs/adr/README.md`.
- Re-run: 97 unit tests OK; smoke client lists 92 tools.
