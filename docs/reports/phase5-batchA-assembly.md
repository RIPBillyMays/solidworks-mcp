# Phase 5 Batch A: assembly tools (offline)

Files: `solidworks_mcp/sw_assembly.py`, `tests/test_sw2017_batchA_assembly.py`. No live SOLIDWORKS used.

## What changed
- `list_mates`: type, alignment, flipped, suppressed, entity components + reference type, min/max variation (SI), dimensions (`name` like `D1@Distance1`, `full_name`, `value_mm`/`value_deg`), plus top-level `dimension_name`, `distance_mm`, `angle_deg`. Names come from the owning feature (IMate2 has no Name).
- `edit_mate` (new): value-only change edits the mate's dimension via `SetSystemValue3`; flip / alignment / limits re-apply via `AssemblyDoc.EditMate4` on the selected mate.
- `set_mate_suppression` (new): select the mate feature, `EditSuppress2` / `EditUnsuppress2`, `IsSuppressed` readback.
- `add_mate`: `entities` (component + face/edge/vertex index, plane name, or point, with `mark`), `min/max_distance_mm`, `min/max_angle_deg`, `width_option`; reports the new mate's feature name and dimensions. `selection` still works; `required` is now only `mate_type`.
- `insert_component`: now passes option 2 when a configuration is named (before it was ignored); reports configuration used and `is_assembly`; subassemblies (.sldasm) supported.
- `list_components`: adds configuration, hidden, virtual, suppression_state, depth, full transform.
- New: `move_component`, `rotate_component` (pure-Python transform math, `SetTransformAndSolve2`; refuses fixed/suppressed; warns when mates push back), `set_component_configuration`, `set_component_visibility`, `set_component_suppression`, `replace_component`, `open_component`, `interference_detection`.
- Skipped: `create_subassembly`. `MakeAssemblyFromSelectedComponents` / `InsertNewVirtualAssembly` signatures cannot be confirmed from the member-name snapshot; needs a live typelib probe first.
- Enum values are inline locals (not module tables) so `test_sw2017_enums` needs no new entries.

## FORK_CHANGES lines
- `sw_assembly.py`: `list_mates` returns type/alignment/flipped/suppressed/entities/dimension names+values (via the owning feature's display dimensions).
- `sw_assembly.py`: `add_mate` accepts `entities`, limit min/max, `width_option`; returns created mate name; `selection` no longer required.
- `sw_assembly.py`: `insert_component` uses AddComponent5 option 2 for a named configuration; shared `_open_silently`/`_set_component_matrix` helpers.
- `sw_assembly.py`: `list_components` adds configuration/hidden/virtual/suppression_state/depth/transform.
- `sw_assembly.py`: new tools `edit_mate`, `set_mate_suppression`, `move_component`, `rotate_component`, `set_component_configuration`, `set_component_visibility`, `set_component_suppression`, `replace_component`, `open_component`, `interference_detection`.

## Live verification checklist (serial, sandbox assembly with 2 parts)
1. `list_mates` after adding a 12 mm distance mate: `dimension_name` `D1@Distance1`, `distance_mm` 12. Confirm `IMate2.Flipped`, `Alignment`, `MateEntity(i)`, `ReferenceComponent`, `GetFirstDisplayDimension` all return data (all read through `safe`, so a miss shows as a missing key).
2. `edit_mate` distance 20: `measure` between faces changes by 8 mm; `set_dimension "D1@Distance1"` agrees.
3. `edit_mate` flip / alignment: verify EditMate4 argument order and that the mate is not left over-defined; verify the status code convention (1 = no error); confirm it works when the mate is selected through `Select2` on the feature.
4. `edit_mate` limit min/max and `add_mate` limit distance: confirm `MinimumVariation`/`MaximumVariation` and which dimensions appear.
5. `add_mate` with `entities`: component-face index order matches `list_faces` expectations; plane select-by-ID string `Front Plane@Part-1@Assem1`; width mate with marks 1/2 and each `width_option`.
6. `set_mate_suppression`: component moves when suppressed; `IsSuppressed` readback true.
7. `insert_component` of a .sldasm and with `configuration`: `list_components` shows configuration; mass matches that configuration.
8. `move_component` / `rotate_component` on a floating part: `Transform2` readback equals request; with a mate present, expect the warning.
9. `set_component_configuration`: put of `ReferencedConfiguration` via late binding works (else try `UseNamedConfiguration`).
10. `set_component_visibility`: `HideComponent2` / `ShowComponent2` act on the selection; `Visible` 0/1 readback; mass unchanged.
11. `set_component_suppression`: `SetSuppression2` 0 / 2; mass changes; confirm state 2 vs 3 (resolved) is right.
12. `replace_component`: `ReplaceComponents2` 4th argument (0 = match by name is unverified), possible mate-repair dialog (modal risk), path and mate count preserved.
13. `open_component`: new window opens, active doc title correct, `list_open_documents` lists it.
14. `interference_detection` with two overlapping boxes: pair and volume in mm^3 correct; setters on the manager accepted; `Done()` leaves SOLIDWORKS out of the checker.
