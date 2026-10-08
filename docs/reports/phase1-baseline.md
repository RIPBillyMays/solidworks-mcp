# Phase 1 baseline: install and offline checks

Date: 2026-10-08
Target SOLIDWORKS: 2017 SP05 (not running; no live checks performed in this phase)

## Environment

- OS: Windows 11 Pro 10.0.26200
- Python: 3.12.13 (CPython, MSC v.1944 64 bit), venv at `.venv` created with `uv venv --python 3.12 .venv`
- Install: `uv pip install --python .venv\Scripts\python.exe -e .` (editable, solidworks-mcp 0.1.0)
- Key package versions:
  - mcp 1.30.0 (pinned range in pyproject: `>=1.29,<2`)
  - pywin32 312 (`>=306`)
  - pillow 12.3.0 (`>=10`)
- Other notable resolved packages: pydantic 2.14.0, anyio 4.15.1, httpx 0.28.1, starlette 1.7.0, uvicorn 0.54.0 (32 packages total)

## Results

| Step | Result |
|---|---|
| venv + editable install | PASS |
| Offline unit tests (`python -m unittest discover -s tests -v`) | PASS: 24 run, 24 ok, 0 failures, 0 errors |
| `import solidworks_mcp.server` | PASS (no output, no warnings with `-W default`) |
| MCP stdio smoke (`tools/compat/mcp_smoke_client.py`) | PASS: initialize + list_tools succeeded without SOLIDWORKS |

`tests/live_p0_regression.py` was not run (requires live SOLIDWORKS). `unittest discover` only collects `test*.py`, so it is not picked up.

## MCP server smoke output

- serverInfo: `solidworks-mcp` version `1.30.0` (this is the `mcp` library version, not the package version 0.1.0; the server does not set its own version in `Server("solidworks-mcp")`)
- Protocol version negotiated: 2025-11-25
- Server `instructions`: none (the initialize result carries no instructions)
- Tool count: 92
- Server startup with no SOLIDWORKS running produced nothing on stderr. No COM attach is attempted until a tool is called.

Tool names (sorted):

activate_drawing_view, activate_sheet, add_dimension, add_mate, add_note, add_relation, add_sheet, auto_dimension_view, boss_extrude, capture_screenshot, chamfer, check_errors, circular_pattern, close_sketch, convert_entities, create_axis, create_drawing, create_drawing_sketch, create_new_document, create_plane, create_sketch, cut_extrude, delete_feature, draft, draw_3point_arc, draw_arc, draw_centerline, draw_circle, draw_ellipse, draw_line, draw_point, draw_polygon, draw_rectangle, draw_slot, draw_spline, edit_sketch, export_document, fillet, get_active_document_info, get_bounding_box, get_mass_properties, get_sketch_status, insert_center_marks, insert_centerlines, insert_component, insert_detail_view, insert_model_annotations, insert_model_view, insert_projected_view, insert_section_view, insert_standard_views, linear_pattern, list_bodies, list_components, list_dimensions, list_drawing_views, list_edges, list_faces, list_features, list_mates, list_reference_planes, list_sheets, list_sketch_segments, list_sketches, list_vertices, loft, measure, mirror_feature, open_document, rebuild_document, rename_feature, revolve, rib, save_active_document, save_document, set_appearance, set_component_fixed, set_construction_geometry, set_dimension, set_drawing_view, set_feature_suppression, set_material, set_view, shell, simple_hole, sketch_chamfer, sketch_fillet, sketch_mirror, sketch_offset, sketch_trim, solidworks_status, sweep

## Warnings and problems

- None blocking. `uv` writes progress to stderr, which PowerShell 5.1 surfaces as a `NativeCommandError` wrapper around otherwise successful output; the install exited cleanly.
- Minor observation: the reported server version (1.30.0) is the MCP SDK version, which could confuse version-based compatibility checks. Use the package version (0.1.0) from `pip list` instead.
- The unit tests are pure-Python (mock-based, 0.01s); they say nothing about compatibility with the SOLIDWORKS 2017 COM API. That is covered by the live phase.

## Files added in this phase

- `tools/compat/mcp_smoke_client.py` (stdio client: initialize + list_tools only, never calls a tool)
- `docs/reports/phase1-baseline.md` (this file)
- `.venv/` (local, untracked)
