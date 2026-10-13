# Phase 5 Batch A: export (offline implementation)

Status: implemented and unit-tested offline; NOT verified live.

## What changed
- `solidworks_mcp/sw_export.py` (new, no COM I/O): format table, `plan_export` (validates options per format and document type, builds preference changes), `PreferenceScope` (set, then restore in reverse order), `format_catalog`.
- `solidworks_mcp/sw_file.py`: `export_document` rewritten (backward compatible: `path`/`overwrite` alone behave as before; no preference or configuration work happens unless an option is passed). New tools `list_export_formats`, `export_bodies`, `export_components`. No `server.py` change needed (sw_file already imported).
- `tests/test_sw2017_batchA_export.py`: 25 tests (enum ids pinned to `sw2017_enums.txt`, planning, restore-on-failure, configuration restore, per-body, per-component, output-root check, registration).

## Behaviour
- Formats by extension: step/stp, iges/igs, x_t, x_b, sat, stl, 3mf, wrl, eprt (part), easm (assembly), pdf, png, jpg/jpeg, tif/tiff, bmp.
- Options: `step_version` AP203|AP214 (swStepAP 75 = 203/214); STL `stl_format`, `stl_quality` coarse|fine|custom, `deviation_mm`, `angle_deg` (either implies custom), `units` mm|cm|m|in, `single_file`, `translate_to_positive`; VRML `units`, `vrml_version`, `single_file`; `configuration` (ShowConfiguration2, previous config restored); `pdf_3d`.
- Unknown or inapplicable options are rejected with a clear message (never silently ignored). `units` is rejected for STEP/IGES/3MF (no verified preference).
- PDF of a part/assembly: `GetExportFileData(1)` + `ExportAs3D=True`, passed to `Extension.SaveAs`. On failure the message suggests `pdf_3d=false`.
- `export_bodies`: `IBody2.Save`, x_t/x_b only. Other per-body formats are refused rather than guessed: the 2017 snapshot has no `IBody2.Save3/SaveToFile`, and SaveAs of a selection is not known to honour the selection, which would silently export the whole part N times.
- `export_components`: distinct components (deduplicated by file path), uses `IComponent2.GetModelDoc2` then the same `_save_as`; skips suppressed, lightweight (unloaded) and wrong-type components and reports them. No PDF/images, no `configuration`.
- Not supported (reported by `list_export_formats`): OBJ, STEP AP242. IGES options and DXF/DWG not done (no verified preference ids in the typelib dump).
- All writes go through `validated_output_path` (OUTPUT_ROOT).

## Compat
All members used are in `sw2017_api_members.txt`: `ISldWorks.GetExportFileData`, `Get/SetUserPreference{Integer,Double}Value`, `Get/SetUserPreferenceToggle`, `IModelDoc2.ShowConfiguration2/GetConfigurationNames/GetActiveConfiguration`, `IBody2.Save`, `IComponent2.GetModelDoc2`, `IExportPdfData.ExportAs3D/ViewPdfAfterSaving`. Preference members are flagged via `flag_methods`.

## Test results
Batch A tests: 25/25 pass. Full suite: 139 run, 1 failure, in `test_sw2017_enums` complaining about new unchecked constants in `sw_feature.py` (`MARK_END_1`, `MARK_END_2`, another agent's file; not from this batch). Smoke client lists all four tools.

## FORK_CHANGES lines
- `solidworks_mcp/sw_export.py`: new module (fork addition). Export format table, option validation, user-preference scoping for SOLIDWORKS 2017.
- `solidworks_mcp/sw_file.py`: `export_document` extended (format options, configuration, 3D PDF, preference set/restore); added `list_export_formats`, `export_bodies`, `export_components`; imports `sw_export`, `flag_methods`, `get_bodies`, `iter_components`.
- `tests/test_sw2017_batchA_export.py`: new offline tests.

## Live verification checklist (SW 2017, serial, sandbox/ only)
Unverified assumptions first:
1. `swStepAP` value semantics: set AP203 then AP214 and check file header (`CONFIG_CONTROL_DESIGN` vs `AUTOMOTIVE_DESIGN`). If the preference expects a different encoding, fix `STEP_VERSIONS`.
2. STL double prefs (`swSTLDeviation`, `swSTLAngleTolerance`): confirm units (code assumes metres and radians). Custom quality with tiny deviation must give more triangles than coarse.
3. STL binary: size = 84 + 50 x triangles; ascii starts with `solid`. `units` in vs mm changes bbox in file by 25.4.
4. `swExportStlUnits` / `swExportVrmlUnits` accept `swLengthUnit_e` values (mm 0, cm 1, m 2, in 3); VRML version ids.
5. Read back each preference after the call: all restored to the user's value (check `preferences_restored` and via UI).
6. `SetUserPreferenceToggle` / `Get...` call shapes work through late binding (two args) and do not raise.
7. `.sat`, `.wrl`, `.eprt`, `.easm`, `.tif`, `.x_b` via Extension.SaveAs: file exists, non-empty, header sane (`#VRML V2.0`, `PK`/eDrawings magic).
8. 3D PDF: begins `%PDF`, has `/U3D` or `/PRC`; if unavailable confirm the failure message and that `pdf_3d=false` works.
9. `configuration`: export a non-active config, active config afterwards unchanged, no rebuild prompt.
10. `export_bodies` on a 3-body part: 3 files; reimport volumes equal `list_bodies`. Confirm `IBody2.Save` honours `.x_t` vs `.x_b` by extension and does not raise a dialog.
11. `export_components` on a test assembly with duplicates, a suppressed and a lightweight component: file per distinct part; part volume equals its own mass properties. Check `GetModelDoc2` returns the doc for resolved components and None for lightweight.
12. Re-run T3 export steps (STEP/IGES/STL/X_T/PNG/JPG/BMP/3MF) to confirm backward compatibility.
