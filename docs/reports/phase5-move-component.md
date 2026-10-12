# move_component diagnosis (Phase 5)

Verdict: expected solver behaviour, not a bug in the transform math. The tool only failed to report it clearly (it already warned, but gave no requested-vs-achieved position).

## Measured (live SW 2017, probes in sandbox/phase5/move/, origin_mm of Block-1 via Transform2 after rebuild)
| Case | Request | Before | After | Persists | Tool result |
|---|---|---|---|---|---|
| 1 floating, unmated | x+30 | - | - | - | refused: "fixed" (SW inserts the first component fixed; unfix first). Unmated move proven by A10a in batchA-live |
| 2 coincident (free x,y) | x+30 | [0,0,10] | [30,0,10] | yes | ok, no warning |
| 2 | x-10,y+5 | [30,0,10] | [20,5,10] | yes | ok |
| 2 | z+20 (locked dir) | [20,5,10] | [20,5,10] | - | ok + warning |
| 3 limit_distance, range x in [15,25], stored x=20 | absolute x=22 (in range) | [20,0,10] | [20,0,10] | - | ok + warning |
| 3 | x+2 / x+60 / x-80 | [20,0,10] | [20,0,10] | - | ok + warning |
| 3 | y+15 (free) | [20,0,10] | [20,15,10] | yes | ok, no warning |

Raw API: SetTransformAndSolve2 returns True yet position stays 20; setting Transform2 directly shows 22 until rebuild, then snaps back to 20. IAssemblyDoc.TranslateComponent via COM: "Type mismatch" (not pursued).

## Root cause
A programmatic transform is re-solved against all mates. A limit_distance/limit_angle mate resolves to its stored value (distance 10 -> x=20) in that solve; the min/max range only takes effect during interactive drags. So even an in-range move is undone. C1 items 1.1b/c were therefore not a clamp test and cannot be one through move_component. Free directions of other mates move fine.

## Change
- solidworks_mcp/sw_assembly.py (upstream-derived, already carries the fork header): on mismatch the result now includes data.requested_origin_mm next to origin_mm, and the warning names the limit-mate snap-back; tool description documents the re-solve behaviour. Behaviour (ok=True + warning) unchanged.
- tests/test_sw2017_batchA_assembly.py: warn test asserts requested_origin_mm/origin_mm.
- Suite green. No commits.
- To really test limit ranges later: use edit_mate to change the mate value (or a drag-based API), not move_component.
