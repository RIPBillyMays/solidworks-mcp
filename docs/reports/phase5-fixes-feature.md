# Phase 5 field fixes: sw_feature (#5, #8, #9, #17)

Offline only. Tests: `tests/test_sw2017_feature_fixes.py` (33 tests). Full suite 568 OK, MCP smoke OK (170 tools).

## Design

### #5 extrude direction
- New `direction: "+normal" | "-normal"` on `boss_extrude` and `cut_extrude`. `_ExtrudePlan` is shared only with `sw_edit`; `surface_extrude` (sw_surface.py) does not use it and was NOT changed.
- Mapping table `DIRECTION_REVERSE_FLAG` (Dir flag): boss +normal=False, boss -normal=True, cut +normal=True, cut -normal=False. Based on the 2017 field observation (boss default +normal, cut default -normal).
- `reverse` still works. Giving `direction` AND `reverse` (any value, including false) raises a clear error before any COM call. The schema default on `reverse` was removed so MCP clients do not auto-fill it.
- Result data: `direction` (+normal / -normal / symmetric for mid_plane and through_all_both), `direction_vector` (model coordinates, or null if unreadable), `volume_before_mm3`, `volume_after_mm3`, `volume_delta_mm3` (reuses `_volume_mm3`).
- `direction_vector` comes from the inverse of `ISketch.ModelToSketchTransform`: two IMathPoints, the sketch origin and sketch +Z, are mapped through it with `IMathPoint.MultiplyTransform`, and the difference is normalised. This avoids guessing the row/column layout of `ArrayData`. All members are in the 2017 list.
- Cut auto-reverse: `reversed_automatically` is now always present (true or false) and the direction/vector reflect the direction actually used. An explicit `direction` is never auto-retried; the message says so. Without `direction` the old retry behaviour is unchanged.
- With a second direction, `direction` applies to direction 1 and direction 2 goes the opposite way (documented in the schema).

### #8 delete_feature
- Names resolve through `_resolve_features`: exact match first, otherwise a unique case/whitespace-insensitive match. Ambiguous or unknown names are errors.
- `doc.ClearSelection2(True)`, then `Select2(False, 0)` for the first feature and `Select2(True, 0)` for the rest (a plain False for each would drop the earlier picks).
- Single `DeleteSelection2(0)` call (test_sw2017_enums pins this). Afterwards the tool compares feature lists before and after.
- Returns `deleted` (name + type), `also_deleted` (dependents that were not requested), `still_present`, and the feature counts before and after.
- Fails if a requested feature is still present or the count fell by less than the number requested.

### #9 set_feature_suppression
- `_is_suppressed` calls `IsSuppressed2(3, [active config])`, flagged as a method, with `IsSuppressed` as the fallback. `GetSuppression2` is not used because it does not exist in 2017.
- State is snapshotted before and after, for the tail of the tree from the first requested feature (children come after parents).
- Features already in the target state are skipped. The result carries `already_in_state` and `already` (true when all of them were).
- `changed` lists the features that really changed. `side_effects` lists non-requested features whose state flipped. `mismatched` lists features whose final state is wrong, and the call fails only on those.
- If the state is unreadable, the API return value is trusted and the feature is listed under `unverified`.

### #17 fillets
- `fillet_variant type=variable`: the meaning of the Radii array for several vertices is not documented, so `vertex_radii` is NOT supported (an explicit `vertex_radii` is refused). Chains are rejected with a message suggesting per-edge calls: first when more than one edge index is given, then again if the selection count after propagation is above 1. The existing single-edge path is unchanged.
- `fillet` with `propagate=false`: options passed are exactly `FILLET_UNIFORM_RADIUS` (2), and with propagate `2|1`. 2017 has no separate tangent bit. The description now says SOLIDWORKS may still carry the fillet along tangent edges. The result reports `fillet_options` and `propagate`.

## Files changed
- `solidworks_mcp/sw_feature.py`
- `tests/test_sw2017_feature_fixes.py` (new)
- `docs/reports/phase5-fixes-feature.md` (this file)
- `sw_core.py` untouched.

## Proposed docs/FORK_CHANGES.md bullet
- `sw_feature.py` (Phase 5 field fixes): `direction` (+normal/-normal) on boss/cut extrude with a boss-vs-cut flag table, plus `direction_vector`, `volume_delta_mm3` and `reversed_automatically` in the results; an explicit direction is never auto-reversed. `delete_feature` clears the selection first, matches names exactly before falling back to a unique loose match, and verifies the deletion with before/after lists. `set_feature_suppression` reads `IsSuppressed2` before and after, reports `already`, side-effect children and final-state mismatches. `fillet_variant type=variable` refuses multi-edge chains and `vertex_radii`. `fillet` reports its option bits and documents that 2017 has no tangent-propagation bit.

## Live-probe checklist (live SOLIDWORKS needed; serial, via a Sonnet subagent)
1. Front Plane square sketch, `boss_extrude direction=+normal`: bounding box extends toward +Z, `volume_delta_mm3` > 0, `direction_vector` ~ [0,0,1]. Repeat with `-normal`: toward -Z, vector [0,0,-1].
2. On a body with material on both sides of the plane, `cut_extrude direction=+normal` removes material on the +Z side only (check volume and a probe point). `-normal` does the opposite. Confirm the flags still match the field observation (cut default -Z).
3. Confirm `direction_vector` on a Right Plane and a Top Plane, and on a sketch on a planar face with a flipped normal.
4. `direction` + `reverse` is refused. A cut with no overlap on an explicit direction returns ok:false and is not retried. A default cut that auto-reverses reports `reversed_automatically:true`.
5. `mid_plane` returns `direction: symmetric`.
6. `delete_feature` with a stale sketch selected (via `select_entity`) deletes only the named renamed sketch. Check `deleted`, `also_deleted` and the counts, plus a dependent-delete case.
7. `set_feature_suppression`: suppress a parent with children (side_effects lists them), call again (already:true, ok), unsuppress. Check that `IsSuppressed2(3, [cfg])` actually returns a per-config list in 2017; the fallback `IsSuppressed` is used otherwise.
8. `fillet propagate=false` on an end edge next to tangent edges already filleted R1.2: compare against a uniform R4 for the tangent-propagation difference. If 2017 still propagates, document it as a limitation or give the agent a workaround (select the faces or edges explicitly).
9. `fillet_variant type=variable` on a single edge with propagate=false. Check the refusal message on a multi-edge selection.
