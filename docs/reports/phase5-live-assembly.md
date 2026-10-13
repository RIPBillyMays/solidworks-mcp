# Phase 5 live assembly run (tests/live_p5_assembly.py, SW 2017, in-process handlers)
Files: sandbox/phase5/asm/{A.sldprt,B.sldprt,asm.sldasm,live_log.txt}. No dialogs/hangs.

| Step | Result | Measured |
|---|---|---|
| 1 baseline | PASS | 0 open docs |
| 2 part A / B volume | PASS | 59214.602 (exp 59214.602) / 2356.195 (exp 2356.194); files 55 KB / 69 KB |
| 3 close A,B save=false | PASS | closed, count back to baseline |
| 3 dirty close refused / force | PASS | Part3 dirty=True; refused, still open; force closed it |
| 4 insert A (0,0,0), B (50,0,40) | PASS | origin_mm exact; A fixed |
| 4a concentric | PASS | B origin (0,0,5): axis on hole axis |
| 4b coincident pin bottom / plate top (anti_aligned) | PASS | B origin z=10 |
| 4c distance 40 (pin top to plate bottom) | PASS w/ note | consistent but flagged "over-define" (redundant with coincident); position unchanged, check_errors clean |
| 4d angle/parallel | SKIPPED | no non-axial planar pair (pin cylinder, plate faces +/-Z only) |
| list_mates | PASS | Concentric1, Coincident1, Distance1 |
| 5 set_dimension "D1@Distance1" | PASS | works for mate dims. With Coincident1 deleted, 40->45 moved B origin z 10->15 (exact), 0 errors |
| 6 delete_mate Coincident1 | PASS | list_mates shows 2 left; 0 rebuild errors; unknown name refused cleanly |
| 7 save assembly, close all | PASS | asm.sldasm non-empty; final docs == baseline (0) |

## Bugs
1. FIXED: insert_component left the opened part as active doc (OpenDoc6), so the 2nd insert raised "requires an active assembly". Fix: ActivateDoc3 back to the assembly after the silent open (sw_assembly.py, logged in FORK_CHANGES.md).
2. Minor: assembly title changes on save (Assem2 -> asm); script's title-based cleanup then missed it and used a not-in-baseline sweep (worked). Not a tool bug.
3. Note: add_mate over-define warning for a redundant-but-consistent mate is conservative; list_mates does not expose dimension names (D1@<mate name> works).
