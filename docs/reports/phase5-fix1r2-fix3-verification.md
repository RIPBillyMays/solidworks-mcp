# Verification: fix 1 Revision 2 and fix 3 (offline)

Suite: 508 tests OK. mcp_smoke_client: 170 tools, activate_document listed.

## A. _line_segments (sw_sketch.py:373-384)
- PASS: keeps GetType==0, drops the circle (type 1 in FakeCircle). Used in _verify_rectangle (404) and _verify_polygon (430); `sides` now len(filtered).
- PASS (no false pass): an unreadable type is kept. If it is the circle, _line_ends raises, _vertices_of returns None, result is ok with verified:false (never a wrong-geometry pass). Can only fail or go unverified, not falsely verify.
- Minor: `int(seg_type)` is outside try; a non-numeric GetType would raise to server (com_error), not a pass.
- Tests: PolygonTests cover circle filtering and wrong radius. NOT covered: rectangle with an extra circle/arc, unreadable-type segment, unverified path. Suggest adding.
- Pre-existing, unfixed: `inscribed=false` has no effect on 2017 (live report check 9), so that mode will report a false circumradius mismatch.

## B. active_document stamping
1. Stale leak: PASS for handler calls (begin_call under COM_LOCK, before handler; the except branches reuse the same call's title, fine). BUG: server.py unknown-tool branch calls result() before the lock and before begin_call, so it can carry the previous call's title (server.py ~line 92). Fix: call begin_call() at top of call_tool.
2. Thread/async: PASS. Module global, but handler is synchronous inside COM_LOCK, no await between begin_call and result. Would break only if handlers moved to threads.
3. Existing keys: PASS. Only adds top-level key; no exact-dict test matches. solidworks_status keeps its own data.active_document (different level, no clash).
4. ActivateDoc3: PASS. (title, True, 0, byref_long(0)) identical to open_component/export_components/sw_assembly; in _APP_METHODS and compat list. open_document uses False for arg 2 (path), consistent.
5. Fork notes: PASS. server.py:14, sw_core.py:14, sw_file.py:14, sw_sketch.py:15 carry it; FORK_CHANGES.md has line 64 (fix 3) and fix 1 entry per implementation report.
6. Bypass list (no stamp): solidworks_status (sw_file:205, has data.active_document), create_new_document, open_document, close_document (855), activate_document (stamps explicitly), list_open_documents, sw_drawing 147 helper. Tools using running_app() only. Stale-stamp risk: tools that call active_document() then switch docs: export_components (sw_file:663 activates parts, stamp = assembly), insert_component/open_component (sw_assembly 297/1261), drawing _ensure_model_open. Stamp is the document the call started on, which is usually the intended meaning.

## Live checklist
A: draw_polygon n=6 inscribed=true -> ok, verified, sides 6; draw_rectangle in a sketch -> verified; (optionally) polygon inscribed=false documents the known mismatch.
B: two docs open; get_active_document_info shows A; activate_document B (mixed case) -> ok, then a feature tool shows active_document B; activate_document with bad title -> ok:false; call unknown tool right after a doc tool -> must have no active_document (currently may); list_open_documents has no field.
