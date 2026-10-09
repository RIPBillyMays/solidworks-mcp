# Phase 2 verification (T2), independent verifier

Date 2026-10-08, branch `phase-2-static-compat`. Offline only; SOLIDWORKS never touched.

## Verdict: PASS

## 1. Test suite
`.venv\Scripts\python.exe -m unittest discover -s tests -v`: Ran 74, failures 0, errors 0, skips 0, expected failures 0, unexpected successes 0. Result `OK`. `grep expectedFailure|skip` over `tests/` finds only a docstring line in `test_sw2017_enums.py:26` saying there are none.

## 2. Smoke client
`tools\compat\mcp_smoke_client.py`: server solidworks-mcp 1.30.0, tool count 92. All 6 `call_versioned` sites resolve to their newest candidate in the 2017 typelib.

## 3. Mutation checks (each reverted)
Baseline `git diff --stat` (8 files, 84 insertions, 23 deletions) saved with md5s of every `solidworks_mcp/*.py` and `tests/*.py` before starting.
| Mutation | Result |
|---|---|
| a. `extension(doc).SaveAs(` -> `.SaveAs3(` at sw_file.py:97 | FAIL `test_every_called_member_exists_in_sw2017` (`SaveAs3 sw_file.py:97, checked against IModelDocExtension`) + `test_known_misses_are_fixed` |
| a2. appended `def _mut(): doc.Extension.SaveAs3(...)` to sw_inspect.py | FAIL, same two tests (`sw_inspect.py:463 via attribute`) |
| b. `"SaveAs3"` back in `_EXTENSION_METHODS` | FAIL, same compat tests (`sw_core.py:362 via _EXTENSION_METHODS`); also `test_saveas3_is_not_flagged_on_the_extension` is designed to fail |
| c. revolve `direction_type = 4 if mid_plane` | FAIL `test_revolve_mid_plane_uses_swEndCondMidPlane` |
| d. function-level `from sw_core import result` in `measure()` | FAIL `test_every_function_level_import_resolves_as_a_package_import` (+1 ERROR in `MeasureTests`) |
After reverting: `git diff` md5 identical to baseline (`a3fef79f...`), `git diff --stat` identical, md5 of all source/test files identical, suite back to `OK` (74).

## 4. Diff discipline (uncommitted diff)
Upstream files touched: `sw_core.py`, `sw_drawing.py`, `sw_feature.py`, `sw_file.py`, `sw_inspect.py`. Each has the `# Modified for SOLIDWORKS 2017 support (fork).` line (grep count 1 each) and FORK_CHANGES.md rows (lines 8-10 for A, 12-17 for C). Not touched: `.gitignore`, `README`, `pyproject`, `tools/tlb_probe.py`, `tests/test_sw_core.py`, other handler modules. Other modified files are ours: `tools/compat/dump_sw_tlb.py`, `docs/FORK_CHANGES.md`, `docs/PLAN.md`.
Every source change maps to 2.3, 2.5 (template ids, `IMeasure.Calculate`) or C's 6 documented fixes (2.6 items 8, 6, 7, 4, 2, 5). Observations (non-blocking):
* `docs/PLAN.md` diff also flips T5a "Claude Code" to done, unrelated to Phase 2.
* The three committed cherry-picks modify `sw_assembly.py`, `sw_refgeom.py`, `sw_sketch.py`, `README.md` and `tests/test_sw_core.py` without fork headers. They are logged in FORK_CHANGES.md row 11 as upstream commits, so this is acceptable.

## 5. Spot-check against typelib text files
Present in `sw2017_api_members.txt`: `IMeasure.Calculate`, `IView.SetDisplayMode3`, `IView.SetDisplayTangentEdges2`, `IModelDoc2.ActiveView`, `IModelView.DisplayMode`, `ISldWorks.GetUserPreferenceStringValue`. Absent as claimed: `IModelDocExtension.SaveAs3`, `IView.TangentEdgeDisplay`, `IModelDoc2.ViewDisplayShadedwithedges`.
Enums in `sw2017_enums.txt` match the code: DefaultTemplatePart/Assembly/Drawing 8/9/10; swEndCondMidPlane 6; swCreateSectionView_ExcludeFasteners 64; swDetViewLEADER 2; swDetCircleCIRCLE 1; swDisplayMode_e wireframe 0, hidden-greyed 1, hidden 2, shaded 3; swDisplayTangentEdges_e Hidden 0, VisibleAndFonted 1, Visible 2; swViewDisplayMode_ShadedWithEdges 5; END_CONDITIONS and `SW_INPUT_DIM_VAL_ON_CREATE` 10 spot-checked.
Non-vacuity: scanner collects 551 refs (234 distinct names) and 6 `call_versioned` sites; the test asserts >300 refs, a list of expected names and >=6 versioned sites, and the snapshot is >5000 members. Allowlist (`compat_allowlist.txt`) is header-only with zero entries, so it contains no real SW members; `KNOWN_2017_MISSES` is `{}`.
Note: `swDisplayMode_e.swSHADED_EDGES=7` also exists; the code uses `swSHADED` (3) plus `Edges=True`. This is flagged for Phase 3 live verification in the code comment; not a T2 defect.

## 6. Late-binding safety
New argument-taking calls are routed correctly: `flag_methods(measurement, "Calculate")` before `Calculate(nothing())` (sw_inspect.py:287-288); `flag_methods(target, "SetDisplayTangentEdges2").SetDisplayTangentEdges2(mode)`; `flag_methods(view, "SetDisplayMode3")`. `app.GetUserPreferenceStringValue` is in `_APP_METHODS`. `doc.ActiveView.DisplayMode = 5` is a zero-argument property get plus a property set. No defects found.
