# Phase 5 fix revisions: offline review + live verification

Live runs: tests/live_p5_fix3_activedoc.py (new, calls server.call_tool) and tests/live_p5_fix1_sketch.py, SW 2017, no pre-existing docs, all docs closed afterwards. Saves went to sandbox/fix3_probes/ (set via in-process env SW_MCP_OUTPUT_ROOT, since the default save root is ~/Documents/solidworks-mcp).

## Offline review
| Item | Result | Evidence |
|---|---|---|
| B1 begin_call first in call_tool | PASS | server.py:90 first statement; again under COM_LOCK (96) |
| Polygon circumscribed math | PASS | sw_sketch.py:859 `reach / math.cos(math.pi / sides)` |
| Fork note in modified files | PASS | server.py, sw_assembly.py, sw_core.py, sw_file.py, sw_sketch.py each have the note |
| FORK_CHANGES entries | PARTIAL | server.py/sw_core/sw_file/sw_sketch covered (line 64 + fix 1). Line 64 does not mention the new `stamp_active_document` import and call in sw_assembly.py (insert_component); add one clause |
| Unit tests | PASS | full suite OK |
| mcp_smoke_client | PASS | 170 tools |

## Live
| Check | Result | Evidence |
|---|---|---|
| 1 hexagon inscribed=true r=10 | PASS | ok, verified, sides 6, circumradius 10.0; extrude 5 volume 1299.038 = expected |
| 2 inscribed=false apothem 10 | PASS | ok, verified, circumradius 11.547005; volume 1732.051 = 2*sqrt(3)*100*5 |
| 3 draw_rectangle | PASS | ok, verified, bbox (0,0)-(30,20) |
| 4 activate_document mixed case | PASS | request "fIxA.SlDpRt" -> result and following list_features active_document = FixA.sldprt (B was active) |
| 5 bad title | PASS | ok:false, "No open document is titled ..." |
| 6 unknown tool after doc tool | PASS | no active_document key; list_open_documents also has none |
| 7 create_new_document / open_document stamp | PASS | create: active_document=Part44 = new doc; open_document(FixB) active_document=FixB.sldprt |
| 8 live_p5_fix1_sketch.py full | PASS | checks 1-9 all PASS, including 9 (polygon verified) |

No bugs found. Cleanup: every created doc closed; list_open_documents empty.
