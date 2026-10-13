# Phase 5 Batch C1 live pass (2026-10-11): PARTIAL, STOPPED (SOLIDWORKS process died)

Run in-process via `tests/live_p5_batchC1.py` (stages one at a time). **The SOLIDWORKS 2017 process exited during the cam mate test** (`AddMate5` -> `com_error -2147023170 The remote procedure call failed`; `SLDWORKS` no longer in the process list). Not restarted (ADR-0005). Stages after `cam` were NOT run. Zach must relaunch SW (and save/close anything) before the pass resumes. No modal dialog was seen; the probe docs were all closed before the crash.

| # | Item | Result | Evidence |
|---|---|---|---|
| 1.1a-d | limit_distance / limit_angle | PASS (1.1b/c weak) | built types 5 and 6, mates 1->2; x=20.0 in [15,25]; limit_angle tilt 30.00 deg. 1.1b/c "drag past limit" stayed at 20.0, i.e. `move_component` did not move it at all (not a clamp test); needs a rerun with a drag that really moves |
| 1.2 | gear | PASS-STATIC, dynamic unproven | mate created, built type 10, +1 mate. Ratio 3:2 reads back D1=2000, D2=3000 (num/den land swapped vs. the tool doc), `reverse=False` reads `flipped=true`. Rotating A 90 deg (`SetTransformAndSolve2`, and also `IDragOperator` stepped 5 deg, absolute and relative) never moved B (dB=0.00), so the ratio test cannot be measured via COM. Recommend: keep, document that the ratio/direction is not dynamically verified; or fence if Zach wants only verified behaviour |
| 1.3 | rack_pinion | FENCE-RECOMMENDED (per-type) | `AddMate5` refused: "unknown error" (status 0) with `value_slot=distance`; the `ratio` slot (alt probe) not yet tried |
| 1.4 | screw | PASS-STATIC, dynamic unproven | built type 17, mate created; rotation 360 deg gave dz=0 (same propagation limitation as gear) |
| 1.5 | cam | PER-TYPE-REFUSED | `AddMate5` with cam marks (1, 8) killed the SW process. `add_mate mate_type=cam` now returns `ok:false, "Not supported on SOLIDWORKS 2017: ...", fenced:true` before any selection/COM |
| 1.6-1.15 | hinge, slot, path, sym, width, materef, linear, circular, derived, mirror, subasm | NOT RUN | SW died at 1.5; `hinge`/`path`/`mirror`/`subasm` were the planned likely-fence candidates |

## Probed constants
- `DragOperator`: `IAssemblyDoc.GetDragOperator` is only reachable as `doc._oleobj_.Invoke(81, 0, 1, True)` (dynamic attribute fails with "Member not found"); `BeginDrag/EndDrag` are read as attributes. Works but does not drive gear/screw partners.
- `LIVE_PROBE_CAM_MARKS` (1, 8): crashed SW. Unchanged; the type is refused instead.
- `LIVE_PROBE_VALUE_SLOT[rack_pinion]="distance"`: refused. `"ratio"`: untried. `[screw]="distance"`: accepted.

## Files changed
- `solidworks_mcp/sw_mates_adv.py`: `UNSUPPORTED_MATE_TYPES` (cam).
- `solidworks_mcp/sw_assembly.py`: `add_mate` refuses types in that dict before selection/COM; import added.
- `tests/test_sw2017_batchC_assembly.py`: new `test_cam_mate_refused_before_any_com_call`; `_run` clears the dict so mark tests still run.
- sandbox/probe/ (c1a/c1b/c1c, cleanup, run.sh) probes only.

## Unit tests
479 OK (`.venv\Scripts\python.exe -m unittest discover -s tests`).

## Resume
After Zach relaunches SW: rerun `limit` fix check, then `rack` (try `value_slot=ratio` once), then `hinge slot path sym width materef linear circular derived mirror subasm`, one stage per run (a crash loses the session). Suggest testing `hinge` and `path` early, since a cam-style crash may recur. Open fixture parts in SW are closed by `finish()`; if a stage leaves docs open, run `sandbox/probe/cleanup.py`.


## Stage 1 (resume) 2026-10-11 -- STOPPED: SOLIDWORKS died on the path mate

| Item | Result | Evidence |
|---|---|---|
| rack_pinion | PER-TYPE-REFUSED | AddMate5 "unknown error" (status 0) with value_slot=distance (earlier run) and value_slot=ratio (this run); 2 attempts used |
| hinge | PER-TYPE-REFUSED | "unknown error" with marks (1,2) and (0,1); 2 attempts |
| slot | PASS (built type 21 for center/free/distance/percent) | Constraint positions NOT verified: pin x=0.000 in all four (center expects 0; others not distinguishable) |
| path | PER-TYPE-REFUSED (crash) | AddMate5 killed SLDWORKS.exe (process gone). Refused before COM; never re-probe |
| symmetric, width | NOT RUN | SW died; rerun after relaunch |
| gear/screw motion check | NOT RUN | not cheap before the crash |

Files changed: `solidworks_mcp/sw_mates_adv.py` (UNSUPPORTED_MATE_TYPES += rack_pinion, hinge, path), `tests/test_sw2017_batchC_assembly.py` (3 refusal tests), `tests/live_p5_batchC1.py` (unchanged net). Probe docs: none left open (crash). Sandbox probe `sandbox/probe/hinge2.py`.


## Stage 2 (2026-10-11): symmetric, width, gear motion check. SW stayed alive; no crash, no modal.

| Item | Result | Evidence |
|---|---|---|
| 1.9a symmetric | PASS | built type 8, +1 mate. Plate fixed with Right Plane as the symmetry plane; block A fixed at x=+50, block B (started at -20) solved to x=-50.0 (equal and opposite). |
| 1.9b width (percent 25 / 75) | PASS | built type 11 both times. Tab x = -15.000 / +15.000 mm: travel-based (tab-centre travel -30..+30), not gap-based. LIVE_PROBE_PERCENT_AS_FRACTION confirmed. |
| gear motion check | NOT COUPLED (documented limitation) | gear 1:1 on two disks (concentric to fixed shafts). `rotate_component` Z +90 then `rebuild_document`: A rotated 90.0, partner B dB = 0.0. Same as the earlier SetTransformAndSolve2/drag runs, so gear/screw ratio/direction cannot be verified through COM; mate creation itself (types 10/17) is verified. Screw not re-run (same mechanism). |

Decision for orchestrator: keep gear and screw with a "mate builds, motion coupling not verifiable via API" note (no per-type refusal; creation is reliable).

Files changed: none in the library (no refusals needed). Probe `sandbox/probe/gearmotion.py`. Probe docs: all closed (final docs == baseline, SW still running).
Unit tests: 482 OK (unchanged).


## Stage 3 (2026-10-11): materef, component patterns, mirror, sub-assembly. SW stayed alive; no crash, no modal. Probe docs all closed.

| Item | Result | Evidence |
|---|---|---|
| 1.10 add_mate_reference | PASS (after fix) | InsertMateReference2 worked from the start, but the verifier looked for feature type `MateReference`. In 2017 the tree shows `MateReferences` (MateReferenceGroupFolder) plus `MRef-<1>` (PosGroupFolder). Fix: `MATE_REFERENCE_FEATURE_TYPES` in sw_mates_adv.py. Live: refs 0->1, feature 'MRef-<1>'; bad index refused cleanly |
| 1.11 linear_component_pattern | FENCE-RECOMMENDED (whole tool) | FeatureLinearPattern5 returns None, no components added. Tried component marks 4, 2, 8, with the seed fixed and unfixed (5 attempts). Selection verified correct (edge mark 1, component mark) |
| 1.12 circular_component_pattern | FENCE-RECOMMENDED (whole tool) | FeatureCircularPattern5 returns None. Selection read back OK (face type 2 mark 1, component type 20 mark 4); also tried component marks 2, 0, 8, 16. Same root cause as 1.11 |
| 1.13 pattern_driven_component_pattern | PASS | InsertDerivedPattern2: 'DerivedLPattern1', top-level components 2->4 (3-hole PlateH pattern, seed + 2 new) |
| 1.14 mirror_components | PASS | across Right Plane: +1 component 'Block-2' at x=-30.0 (source x=+30.0, y,z unchanged) |
| 1.15 create_subassembly mode=file | PASS | children Block-1, Block-2 under the new sub-assembly, top level 3->2, mates 2->2, file written (sandbox\Grp_file.SLDASM) |
| 1.15 create_subassembly mode=virtual | PER-MODE-REFUSED | InsertNewVirtualAssembly adds an empty holder (children []), selection ignored. Now refused before COM with fenced=True; default mode is now `file`; 2 unit tests replaced |

Other changes: add_mate description (sw_assembly.py) notes gear/screw motion coupling is unverified via the 2017 API.
Unit tests: 482 OK.

## C1 final summary

| Item | Final status |
|---|---|
| limit_distance / limit_angle | PASS (drag-past-limit clamp not measured) |
| gear | KEEP, builds (type 10); motion/ratio unverified (documented) |
| screw | KEEP, builds (type 17); motion unverified (documented) |
| rack_pinion | REFUSED per-type |
| cam | REFUSED per-type (crashes SW) |
| hinge | REFUSED per-type |
| path | REFUSED per-type (crashes SW) |
| slot | PASS builds (type 21); constraint positions unverified |
| symmetric | PASS |
| width | PASS |
| add_mate_reference | PASS (verifier fixed) |
| linear_component_pattern | RECOMMEND WHOLE-TOOL FENCE (orchestrator, sw2017_fences.py) |
| circular_component_pattern | RECOMMEND WHOLE-TOOL FENCE (orchestrator, sw2017_fences.py) |
| pattern_driven_component_pattern | PASS |
| mirror_components | PASS |
| create_subassembly | PASS file mode; virtual REFUSED per-mode |
