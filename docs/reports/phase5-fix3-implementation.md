# Phase 5 fix 3: active document in results + activate_document

## Design
- `sw_core._call_document_title` (module global), set by `note_active_document()`; `begin_call()` clears it.
- `active_document()` records the title it resolved (GetTitle via `value`; failure records None).
- `result()` adds top-level `active_document` when set. `feature_result` goes through `result()`, so it is covered. Existing keys (`ok`, `message`, `data`) untouched.
- Reset: `server.call_tool` calls `begin_call()` right after taking `COM_LOCK`, before the handler. Tools that never call `active_document()` (e.g. `list_open_documents`) get no field.
- Limitation: tools that read `app.ActiveDoc` directly instead of `active_document()` (e.g. `close_document`, drawing/assembly helpers) do not stamp the title. `activate_document` stamps it explicitly.
- `activate_document(title)` in `sw_file.py`: case-insensitive match via `_open_documents`; `ActivateDoc3(title, True, 0, byref_long(0))` (same call as `open_component`; in `_APP_METHODS` and `sw2017_api_members.txt`); verifies `ActiveDoc` title; `ok:false` for no match, COM exception, or switch not taking effect (returns `requested`/`actual`). Success returns `document_info`.
- Optional `document` argument: not implemented (per brief).

## Files
- `solidworks_mcp/sw_core.py`, `solidworks_mcp/sw_file.py`, `solidworks_mcp/server.py` (import + one `begin_call()` line), `docs/FORK_CHANGES.md`, `tests/test_sw2017_active_document.py` (8 tests).

## Results
- Full suite: 508 tests, OK. Smoke client: 170 tools, `activate_document` listed.

## Revision 1
- B1: `begin_call()` is now the first statement of `server.call_tool` (and again under `COM_LOCK`). Test: unknown tool after a stale title carries no `active_document`.
- B6: new `sw_core.stamp_active_document(app)` (reads `ActiveDoc` title, exception-safe). Used in `new_document`, `open_document` (also on the "could not activate" path), `activate_document` (also on switch-failed: reports the doc actually active), `export_components` (end of call) and `insert_component` in `sw_assembly.py` (small import + one line, outside the original file scope). `close_document` unchanged: `closed` only, no `active_document` (tested).
- Not stamped: other tools that read `app.ActiveDoc` directly or switch mid-call (e.g. `open_component`, drawing tools).
- Results: 512 tests OK; smoke client 170 tools.
