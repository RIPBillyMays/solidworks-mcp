# Phase 5 fixes: file / inspect (findings #10, #18, #19, #21)

Offline implementation. Nothing was run against SOLIDWORKS.

## Design

**#10 rebuild_document** (`sw_file.py`, `sw_core.py`)
- New `sw_core.rebuild_detail(doc)` returns `{ok, raw, error}`: the raw `EditRebuild3` return and the exception text. `rebuild()` is unchanged, so existing callers are unaffected.
- New `sw_core.whats_wrong_split(doc)` returns `(errors, warnings)` using `is_warning`. `whats_wrong()` is unchanged.
- `rebuild_document` now returns `problems` (errors only), `warnings`, `rebuild_returned` and `rebuild_error`. Warnings never fail the call.
- If there are no errors and EditRebuild3 raised or returned False, it tries `ForceRebuild3(False)` (in the compat list: IModelDoc2.ForceRebuild3) under `dialogs_suppressed`, then re-reads errors. It sets `force_rebuild_used: true` on success, or `force_rebuild_error` if that raised. `ok` is true only if there are no errors and either rebuild succeeded.
- `force_all` still uses `Extension.ForceRebuildAll`; its raw return and exception are reported the same way.

**#18 list_faces / list_edges** (`sw_inspect.py`)
- New args: `limit` (default 200), `offset`, `feature`, `within_box {min,max}` in mm.
- Response adds `total` (matches after filters), `truncated`, `offset`. `total_faces` / `total_edges` are kept (whole-part count).
- `feature` uses `IFeature.GetFaces` (compat). For edges it uses `IFace2.GetEdges` on those faces. Matching is by COM object equality (`==` on the PyIDispatch). An unknown feature raises ValueError.
- `within_box`: every reported point (`point_mm`, and `start_mm` / `end_mm` for edges) must lie inside the box. Swapped corners are normalised. Entities with no points never match.
- Backward compatible apart from the 200 cap.

**#19 capture_screenshot `save_as`** (`sw_inspect.py`)
- `save_as` is a bare file name. It is rejected if empty or if it contains `/`, `\`, `..` or `:`. `.png` is appended if missing.
- It is validated before any view change or SOLIDWORKS call. The full-resolution PNG is kept at `OUTPUT_ROOT/screenshots/<name>` and the result adds `saved_path`. Base64 (resized) is still returned. Without `save_as`, the temp file is deleted as before.

**#21** docs only: new section in `docs/clients.md` (copy in, work, copy back; `SW_MCP_OUTPUT_ROOT`). The code default is `~/Documents/solidworks-mcp` (`sw_core.py` `OUTPUT_ROOT`). No multi-root support.

## Files changed
- `solidworks_mcp/sw_core.py` (added `rebuild_detail`, `whats_wrong_split`; two small inserts)
- `solidworks_mcp/sw_file.py` (`rebuild_document`, one import)
- `solidworks_mcp/sw_inspect.py` (listings, screenshot)
- `docs/clients.md`
- `tests/test_sw2017_file_inspect_fixes.py` (new, 20 tests)
- this report

## FORK_CHANGES text (for the orchestrator to paste)

> - `sw_core.py`: added `rebuild_detail()` (raw EditRebuild3 result and exception text) and `whats_wrong_split()` (errors vs warnings). Existing `rebuild()` and `whats_wrong()` are unchanged.
> - `sw_file.py` `rebuild_document`: reports `warnings`, `rebuild_returned`, `rebuild_error`. Warnings no longer fail it. Falls back to `ForceRebuild3` when EditRebuild3 raises or returns False with no errors (finding #10).
> - `sw_inspect.py` `list_faces` / `list_edges`: `limit` (default 200), `offset`, `feature`, `within_box`; return `total` and `truncated` (finding #18).
> - `sw_inspect.py` `capture_screenshot`: optional `save_as` keeps the PNG under `OUTPUT_ROOT/screenshots/` and returns `saved_path` (finding #19).
> - `docs/clients.md`: workflow for CAD kept in another repo, and `SW_MCP_OUTPUT_ROOT` (finding #21).

## Test status
- New tests: 20 pass.
- Smoke client: OK, 170 tools.
- Full suite: 535 run, 2 fail, both in `test_sw2017_api_compat`. They flag `_oleobj_` at `sw_core.py:814` (an entity-identity helper, not mine; it comes from another agent's work in progress). It needs an entry in `tools/compat/compat_allowlist.txt`, with the reason "pywin32 attribute, not a SOLIDWORKS member".

## Live-probe checklist (serial, one agent, sandbox only)
1. `rebuild_document` on a healthy part: `ok`, `rebuild_returned` is present, `warnings` is a list.
2. `rebuild_document` on a part with a warning only (for example a fillet warning): `ok` stays true and the warning is listed under `warnings`.
3. Reproduce finding #10 (empty problems, ok:false before): confirm `rebuild_error` holds the exception text, and that `force_rebuild_used` yields ok.
4. `rebuild_document force_all=true`: unchanged behaviour plus the new fields.
5. `list_faces` / `list_edges` on a part with more than 200 entities: 200 returned, `truncated: true`, `offset` pages through all of them, and the union matches the full count.
6. `feature="Boss-Extrude1"`: the faces returned are the feature's faces (check against a screenshot). Verify the COM `==` identity match works. If it matches nothing, fall back to `IFace2.GetFaceId`, which is in the compat list. Also check the edges for the same feature.
7. `within_box` against a known bounding box: all entries inside, none missed.
8. `capture_screenshot save_as="probe.png"`: the file exists in `sandbox/screenshots/`, is non-empty, and `saved_path` is correct. `save_as="../x"` is rejected without touching SW. Without `save_as`, no leftover file remains.


## Revision 2 (live bug 3, #10 force_all)

`IModelDocExtension.ForceRebuildAll` surfaces as a bool property under 2017 late binding, so `extension(doc).ForceRebuildAll()` raised `TypeError: 'bool' object is not callable`. It is now read with `value(extension(doc), "ForceRebuildAll")`, which also works if it is a method. A raised error now gives `ok:false` for that attempt with `rebuild_error` = "ForceRebuildAll failed: <type>: <text>" (previously it fell back to a rebuild that hid the failure); the ForceRebuild3 second opinion can still rescue a healthy model. Tests cover property-style, method-style and raising members.
