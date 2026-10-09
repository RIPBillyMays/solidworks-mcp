# Phase 2: static 2017 compatibility report (tasks 2.1, 2.2, 2.4, 2.6)

Offline only. SOLIDWORKS was never started or attached to. Evidence: the 2017 SP05 type libraries (`sw2017_api_members.txt`, `sw2017_enums.txt`) and the 2017 help (`api\sldworksapi.chm`, `api\swconst.chm`, extracted read-only into a scratch folder).

## Files added or changed (implementer B)

| File | What |
| --- | --- |
| `tests/test_sw2017_api_compat.py` | 2.1: AST scan of `solidworks_mcp/*.py` against `sw2017_api_members.txt` (15 tests, 7 of them scanner self-tests) |
| `tests/test_sw2017_enums.py` | 2.2 + 2.6: enum constants vs `sw2017_enums.txt` (23 tests, 8 `expectedFailure`) |
| `tools/compat/dump_sw_tlb.py` | also writes enum values (`enum.member=value`) to `sw2017_enums.txt`; the members output is byte-identical (verified: no diff) |
| `tools/compat/sw2017_enums.txt` | 6,813 enum values, generated |
| `tools/compat/compat_allowlist.txt` | non-SOLIDWORKS names; **currently empty (header only)** |
| `docs/reports/phase2-tlb-probe.md` | 2.4: `tlb_probe` output for the relevant interfaces and enums |

Full suite after both implementers: `Ran 74 tests ... OK (expected failures=9)`. The 9 = my 8 in `test_sw2017_enums.py` + 1 in `test_sw2017_api_compat.py`.

## 2.1 What the compat test scans

* PascalCase attribute accesses and calls (attributes of imported modules such as `pythoncom.Nothing`, `win32com.client.VARIANT` are skipped automatically, which is why the allowlist is empty).
* Strings given to `flag_methods`, `value`, `safe`, `feature_property`, `invoke_no_arg`, `getattr` (including both arms of `"A" if c else "B"`).
* The `_*_METHODS` tuples and the `_DIMENSION_METHODS` dict.
* Member names that a `for member in (...)` loop feeds into those helpers by variable (for example `GetStartVertex`/`GetEndVertex`, `GetVisibleEntities2`).
* `call_versioned(...)` candidate names, judged as a group.
* Receiver typing: `extension()`/`.Extension` -> IModelDocExtension, `sketch_manager()`/`.SketchManager` -> ISketchManager, `feature_manager()`/`.FeatureManager` -> IFeatureManager, `.SelectionManager` -> ISelectionMgr, `app` -> ISldWorks, `doc` -> IModelDoc2/IPartDoc/IAssemblyDoc/IDrawingDoc, plus local variables assigned from those. 279 of 547 collected names were checked interface-specifically; the rest are checked against any interface.
* Cross-check done while developing: every PascalCase string constant in the package that is also a 2017 member name was confirmed to be collected, except `EditSuppress2`/`EditUnsuppress2` (found inside an `IfExp`, now handled) and non-member strings (`Edge`, `Face`, `Vertex`, `Sheet`, `Top`: SelectByID2 types, view and feature-type strings).

### Misses

| Name | Where | Checked against | Status |
| --- | --- | --- | --- |
| `ViewDisplayShadedwithedges` | `sw_inspect.py:367` (`set_view`) | IModelDoc2/IPartDoc/IAssemblyDoc/IDrawingDoc | **Real bug**, CONFIRMED (2.6 item 2). Not allowlisted. |
| `TangentEdgeDisplay` | `sw_drawing.py:746` (`set_drawing_view`) | any interface | **Real bug**, CONFIRMED (2.6 item 5). Not allowlisted. |
| `SaveAs3` (`_EXTENSION_METHODS`) | `sw_core.py` | IModelDocExtension | Fixed by implementer A before this report; the compat test no longer sees it. The interface-specific self-test `test_interface_specific_check_catches_wrong_receiver` proves it would be caught (`SaveAs3` exists on IModelDoc2 only). |

The two real misses are held in `KNOWN_2017_MISSES` inside the compat test (name -> reason). The main test tolerates exactly those two names; a separate `@expectedFailure` test `test_known_misses_are_fixed` asserts there are none, so it flips to "unexpected success" when the source is fixed, which is the cue to delete the dict entries. Result: zero un-allowlisted, un-tracked misses.

### Allowlist rationale

`tools/compat/compat_allowlist.txt` is empty on purpose. Skipping imported-module attributes removes all the Python/pywin32 noise, and nothing else needed an exemption. Two guard tests keep it honest: entries must carry a `# reason`, must still be referenced by the source, and **must not be real 2017 members** (an allowlisted name that exists is flagged). The two real misses above are deliberately kept out of it, so the allowlist contains no real SOLIDWORKS member missing from 2017.

### `call_versioned` resolution table

All candidates on both sides exist in 2017, so the newest name resolves first everywhere and the fallback is never taken on this machine.

| Site | Candidates (newest first) | First present in 2017 | Older variant also in 2017 |
| --- | --- | --- | --- |
| `sw_drawing.py:648` | `CreateDetailViewAt4`, `CreateDetailViewAt3` | `CreateDetailViewAt4` | yes |
| `sw_feature.py:186` | `FeatureCut4`, `FeatureCut3` | `FeatureCut4` | yes |
| `sw_feature.py:527` | `InsertCutSwept5`, `InsertCutSwept4` | `InsertCutSwept5` | yes |
| `sw_feature.py:540` | `InsertProtrusionSwept4`, `InsertProtrusionSwept3` | `InsertProtrusionSwept4` | yes |
| `sw_feature.py:643` | `FeatureLinearPattern5`, `FeatureLinearPattern4` | `FeatureLinearPattern5` | yes |
| `sw_feature.py:686` | `FeatureCircularPattern5`, `FeatureCircularPattern4` | `FeatureCircularPattern5` | yes |

## 2.2 Enum constants

Every enum-backed constant and table in `solidworks_mcp/*.py` was pinned to the 2017 value: `END_CONDITIONS`, `SURFACE_TYPES`, `CURVE_TYPES`, `DOC_TYPES`, `BODY_*`, `FILLET_*`, `CHAMFER_*`, `PLANE_*`, `MATE_TYPES`, `MATE_ALIGNMENTS`, `TRIM_CHOICES`, `SW_INPUT_DIM_VAL_ON_CREATE`, A's `SW_DEFAULT_TEMPLATE_*` (8/9/10), `sw_sketch.RELATIONS`, the inline sketch-segment and constrained-status maps, `sw_inspect.NAMED_VIEWS`, `sw_assembly.ADD_MATE_ERRORS`, and in `sw_drawing`: `PAPER_SIZES`, `VIEW_TYPES`, `ANNOTATION_TYPES` (incl. the `dimensions` union), `AUTODIM_*`, the two placement maps, `CENTER_MARK_STYLES`. **All match 2017** except `DISPLAY_MODES` (below). `sw_sketch.DIMENSION_DIRECTIONS` is defined but unused (listed as NOT_ENUM). A coverage test fails if a new numeric module-level constant or table appears without a mapping.

## 2.6 Verdicts on the catalog's unverified claims

Evidence for the parameter-to-enum mapping is `sldworksapi.chm`: the typelib declares all of these parameters as plain `long`, so the enum comes from the help text.

| Catalog item | Claim | Verdict | Evidence | Test |
| --- | --- | --- | --- | --- |
| 8 | revolve `mid_plane` passes 4 | **CONFIRMED** | `FeatureRevolve2.Dir1Type` "as defined in swEndConditions_e"; mid plane = 6, 4 = `swEndCondUpToSurface` (`swRevolveType_e.MidPlane360Degrees` is 4 but is a different enum used by IRevolveFeatureData2). | `test_revolve_mid_plane_uses_swEndCondMidPlane` (xfail) |
| 6 | section view `options = 1 \| (2 if exclude_fasteners)` | **CONFIRMED** | `swCreateSectionViewAtOptions_e`: NotAligned 1 ("section does not snap into alignment with the parent"), OffsetSection 2, ExcludeFasteners 64, Partial 16. | `test_section_view_options_flags` (xfail) |
| 7 | detail view `Style`/`Showtype` | **CONFIRMED** (worse than the catalog's reading) | `CreateDetailViewAt4(X,Y,Z,Style,Scale1,Scale2,LabelIn,Showtype,...)`. The code passes 1 as `Style` = `swDetViewBROKEN` and 2 as `Showtype` = `swDetCircleDONTSHOW`. Its comments show the intent was reversed: leader style (`swDetViewLEADER` = 2) and a drawn circle (`swDetCircleCIRCLE` = 1). | `test_detail_view_style_is_leader`, `test_detail_view_showtype_is_circle` (xfail) |
| 4 | drawing `DISPLAY_MODES` uses the wrong enum | **CONFIRMED** | `IView.SetDisplayMode3.Mode` is `swDisplayMode_e` (wireframe 0, hidden-greyed/HLV 1, hidden/HLR 2, shaded 3); the code uses `swViewDisplayMode_e` (1..5). Only `hidden_lines_removed` (2) is right, by coincidence. Shaded with edges is Mode = `swSHADED` plus `Edges=True` (4th arg), but `Edges` is hard-coded False. | `test_display_mode_values_match_swDisplayMode_e`, `test_shaded_with_edges_sets_the_edges_argument` (xfail) |
| 11 | `DeleteSelection2(0)` | **REFUTED as an enum mismatch** | `swDeleteSelectionOptions_e`: Children 1, Absorbed 2, Advanced 4; 0 is a legal "no flags" value and the call does not prompt. Open behavioural question for Phase 3: the `delete_feature` description promises "anything that depends on them" but no `swDelete_Children` (1) flag is passed. | `test_delete_selection_option_zero_is_legal` (passes) |
| 2 | `ViewDisplayShadedwithedges` is a silent no-op | **CONFIRMED** | Absent from every 2017 interface (case-insensitive check too); the compat scan flags it. The code comment "4 = shaded with edges" is also wrong (4 is Shaded, 5 is ShadedWithEdges). | `test_set_view_does_not_call_missing_ViewDisplayShadedwithedges` (xfail) + the compat `KNOWN_2017_MISSES` test |
| 5 | `TangentEdgeDisplay` is a silent no-op | **CONFIRMED** | No such `IView` member; 2017 has `SetDisplayTangentEdges2(DisplayIn)` taking `swDisplayTangentEdges_e` (Hidden 0, VisibleAndFonted 1, Visible 2). The code's map visible 1 / hidden 2 / phantom 3 does not match that either (the catalog cited `swEdgesTangentEdgeDisplay_e`, which is a user-preference enum, not this method's). | `test_tangent_edge_mapping_matches_swDisplayTangentEdges_e` (xfail) |

Summary: 6 CONFIRMED (items 8, 6, 7, 4, 2, 5), 1 REFUTED (item 11, enum part).

### Exact fixes (not applied; source is out of my scope)

1. **Item 8**, `sw_feature.py` `revolve()`: `direction_type = 6 if mid_plane else 0  # swEndConditions_e: 6 = swEndCondMidPlane`. Also confirm live that `single_direction = not mid_plane` (False for mid plane) is what SOLIDWORKS wants; the help only says Dir2 is ignored for mid plane.
2. **Item 6**, `sw_drawing.py` `insert_section_view()`: `options = 0 | (64 if exclude_fasteners else 0)  # swCreateSectionViewAtOptions_e: 64 = ExcludeFasteners`. Check live whether `depth_mm` needs `swCreateSectionView_Partial` (16).
3. **Item 7**, `sw_drawing.py` `insert_detail_view()`: swap the literals in `detail_args`: 4th (Style) `1` -> `2` (`swDetViewLEADER`), 8th (Showtype) `2` -> `1` (`swDetCircleCIRCLE`); fix both comments. `CreateDetailViewAt3` (the fallback) has the same first 9 arguments, so the slice stays valid.
4. **Item 4**, `sw_drawing.py`: `DISPLAY_MODES = {"wireframe": 0, "hidden_lines_grey": 1, "hidden_lines_removed": 2, "shaded": 3, "shaded_with_edges": 3}` (`swDisplayMode_e`); in `_apply_view_options` pass `Edges = (mode == "shaded_with_edges")` as the 4th `SetDisplayMode3` argument (and set `swDrawingsDefaultDisplayTypeHLREdgesWhenShaded` if the help's remark requires it, to be checked live).
5. **Item 2**, `sw_inspect.py` `set_view()`: replace `doc.ViewDisplayShadedwithedges()` with `doc.ActiveView.DisplayMode = 5  # swViewDisplayMode_e.swViewDisplayMode_ShadedWithEdges` (`IModelDoc2.ActiveView` and `IModelView.DisplayMode` exist in 2017, see the tlb-probe report); keep failures logged, not swallowed.
6. **Item 5**, `sw_drawing.py` `set_drawing_view()`: `target.SetDisplayTangentEdges2({"visible": 2, "hidden": 0, "phantom": 1}[...])` (flag `SetDisplayTangentEdges2` first, it takes an argument).

When each fix lands, delete the matching `@unittest.expectedFailure` (the test will report "unexpected success" until then) and, for items 2 and 5, remove the name from `KNOWN_2017_MISSES` in `test_sw2017_api_compat.py`.

## Mutation check (done)

Temporarily changed `extension(doc).SaveAs(` to `extension(doc).SaveAs9(` in `sw_file.py:97` and added `"BogusMember"` to `_EXTENSION_METHODS` in `sw_core.py`. `test_every_called_member_exists_in_sw2017` failed and listed both (`SaveAs9 sw_file.py:97`, `BogusMember sw_core.py:363`). Both edits were reverted from byte-exact backups; afterwards `git diff solidworks_mcp` contained only implementer A's changes (sw_core.py, sw_file.py, sw_inspect.py: the SaveAs3 removal, template ids, `IMeasure.Calculate`), no `SaveAs9` or `BogusMember` remained, and the suite was green again (74 tests, 9 expected failures). The compat test also carries permanent scanner self-tests that inject the same mistakes into fake source, so the check survives refactors.

## Notes for the orchestrator

* The two compat-test misses are real bugs, so T2's "zero un-allowlisted misses" holds only because they are tracked as `KNOWN_2017_MISSES` plus an expected failure. Fixing items 2 and 5 (cheap) would remove that caveat.
* `tools/tlb_probe.py` calls `GetActiveObject` unconditionally in `candidate_roots()` even when `SW_MCP_INSTALL_DIR` is set; `docs/reports/phase2-tlb-probe.md` was produced by a scratch driver that bypasses that call and reuses the tool's own `inspect_methods`/`inspect_enums`.

## Applied by implementer C

All six "Exact fixes" above were applied as written (no deviations); each member was checked against `sw2017_api_members.txt` and each value against `sw2017_enums.txt`. Files: `sw_feature.py` (revolve), `sw_drawing.py` (section view, detail view, `DISPLAY_MODES` + `_apply_view_options`, `set_drawing_view`), `sw_inspect.py` (`set_view`). Fork headers added to `sw_feature.py` and `sw_drawing.py`; `docs/FORK_CHANGES.md` has one row per item. In the tests, the 8 `expectedFailure` decorators in `test_sw2017_enums.py` and the one in `test_sw2017_api_compat.py` were removed and `KNOWN_2017_MISSES` is now an empty dict (mechanism kept). Suite: 74 tests, OK, 0 expected failures, 0 unexpected successes. Smoke client: 92 tools.

Item 5 detail: item 5 (tangent edges) uses `flag_methods(target, "SetDisplayTangentEdges2")` then a call; `set_view` uses a plain property set (`doc.ActiveView.DisplayMode = 5`), the same pattern as the other property sets in the package.

Phase 3 must check live:
* revolve mid plane: that `single_direction = False` with `Dir1Type = 6` gives a symmetric revolve.
* section view: whether `depth_mm` also needs `swCreateSectionView_Partial` (16); that the default (options 0) snaps to the parent.
* detail view: circle drawn and leader style as intended.
* `shaded_with_edges` on a drawing view: whether `Edges=True` alone shows edges or the `swDrawingsDefaultDisplayTypeHLREdgesWhenShaded` preference is needed.
* `set_view` shaded-with-edges actually changes the part window; `SetDisplayTangentEdges2` visible/hidden/phantom render as expected.

Noticed, not fixed: the `delete_feature` description promises dependents are deleted, but `DeleteSelection2(0)` passes no `swDelete_Children` flag (already listed above as a Phase 3 question). The bare `except: pass` on the `ViewZoomtofit2` call in `set_view` still hides failures.
