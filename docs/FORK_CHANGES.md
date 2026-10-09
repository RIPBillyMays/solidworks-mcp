# Fork changes to upstream files

This is the log of every modification this fork makes to files that came from `Slacker-LLC/solidworks-mcp` (Apache-2.0 §4(b)). New files we add (`docs/`, `rules/`, `tools/compat/`, `tests/test_sw2017_*.py`, `CLAUDE.md`) aren't listed.

| Date | File | Change | Why | ADR / Phase |
|---|---|---|---|---|
| 2026-10-08 | `.gitignore` | Added `sandbox/` | Live-test file I/O stays out of git | ADR-0005 / Phase 1 |
| 2026-10-08 | `solidworks_mcp/sw_core.py` | Removed `"SaveAs3"` from `_EXTENSION_METHODS` | Absent from the 2017 `IModelDocExtension` typelib; only produced an unflaggable-name warning | Phase 2 / task 2.3 |
| 2026-10-08 | `solidworks_mcp/sw_file.py` | `new_document` reads default templates with preference ids 8/9/10 (named constants) instead of 1/2/3 | 1/2/3 are file-location ids, so the preference never yielded a template and disk discovery always decided | Phase 2 / task 2.5 |
| 2026-10-08 | `solidworks_mcp/sw_inspect.py` | `measure` flags `IMeasure.Calculate` as a method and calls it with `nothing()` | `Calculate(Entities)` takes one argument in 2017 (null = current selection); the bare call was expected to fail | Phase 2 / task 2.5 |
| 2026-10-08 | `solidworks_mcp/*.py` (several) | Three upstream commits cherry-picked from upstream branch `codex/continue-sw-compat`: `10c2beb` (9 `from sw_core import` sites to relative imports), `4831e37` (set_material readback), `d07a29b` (`call_versioned()` fallbacks in sw_core). Not fork modifications; listed for merge awareness | Fixes the broken local imports and adds older-API fallbacks, verified live on SW 2016 by the upstream author | Phase 2 / task 2.5 |
| 2026-10-08 | `solidworks_mcp/sw_feature.py` | `revolve`: mid-plane end condition 4 -> 6 (`swEndCondMidPlane`); fork header added | `FeatureRevolve2.Dir1Type` is `swEndConditions_e`; 4 is `swEndCondUpToSurface` | Phase 2 / task 2.6 item 8 |
| 2026-10-08 | `solidworks_mcp/sw_drawing.py` | `insert_section_view`: `options = 0 \| (64 if exclude_fasteners)` instead of `1 \| (2 ...)`; fork header added | `swCreateSectionViewAtOptions_e`: 1 = NotAligned, 2 = OffsetSection, 64 = ExcludeFasteners | Phase 2 / task 2.6 item 6 |
| 2026-10-08 | `solidworks_mcp/sw_drawing.py` | `insert_detail_view`: Style 1 -> 2 (`swDetViewLEADER`), Showtype 2 -> 1 (`swDetCircleCIRCLE`); comments corrected | The two literals were swapped relative to `CreateDetailViewAt4`'s parameter order | Phase 2 / task 2.6 item 7 |
| 2026-10-08 | `solidworks_mcp/sw_drawing.py` | `DISPLAY_MODES` now `swDisplayMode_e` values; `_apply_view_options` passes `Edges=True` only for `shaded_with_edges` | `IView.SetDisplayMode3` takes `swDisplayMode_e`, not `swViewDisplayMode_e`; edges are a separate argument | Phase 2 / task 2.6 item 4 |
| 2026-10-08 | `solidworks_mcp/sw_inspect.py` | `set_view`: `doc.ActiveView.DisplayMode = 5` replaces `ViewDisplayShadedwithedges()`; failure is logged | The old member does not exist in 2017, so the call was a silent no-op | Phase 2 / task 2.6 item 2 |
| 2026-10-08 | `solidworks_mcp/sw_drawing.py` | `set_drawing_view`: tangent edges via flagged `SetDisplayTangentEdges2` with `swDisplayTangentEdges_e` values (visible 2, hidden 0, phantom 1) | `IView.TangentEdgeDisplay` does not exist in 2017 | Phase 2 / task 2.6 item 5 |
