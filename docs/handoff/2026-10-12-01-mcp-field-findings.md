# Handoff: 2026-10-12-01 Field findings: MCP bugs and quirks from a real multi-part build

## Resume prompt (paste into a fresh session)
`Read CLAUDE.md, then docs/handoff/2026-10-12-01-mcp-field-findings.md, then continue from "Next steps".`

## Where we are
- **Phase / gate:** Phase 5. These findings come from real, unscripted use of the MCP, driven from another project. They feed 🧑 G5, the Phase 6 rulebook and Phase 7 hardening.
- **Branch / uncommitted changes:**
  - No code has changed. This handoff is the only new file.
  - Batch C work and the `move_component` reporting change were already uncommitted on `phase-5-clients-guided` (see 2026-10-11-06). Run `git status` before starting.
- **SOLIDWORKS state:** running, no documents open, no preferences changed. `sandbox/` holds nothing from this session.

## The usage that produced these findings
An orchestrator (Opus) with Sonnet subagents, one at a time on SOLIDWORKS, used only this MCP to rebuild an existing product in SOLIDWORKS 2017.
- **What was built:** 6 parts and a 20-component assembly.
- **Size and shape:** parts were up to about 240 mm long. They included star-shaped profiles (10-gon, R0.6 tip fillets), rounded rectangles (R16), and 45° chamfer polygons with steps of 0.2–0.6 mm.
- **Features used:**
  - extrudes and cuts (blind, mid_plane, through_all_both)
  - offset planes
  - a loft
  - constant and variable fillets
  - sketch offset and sketch fillet
  - linear feature patterns
  - rotated component instances
  - interference detection
- **Cost:** about 1 100 tool calls over 6 agent runs, most of them wasted on sketch geometry. Giving later agents the quirks list below cut a comparable part from about 300 to about 110 calls.
- **What worked well:**
  - `boss_extrude` and `cut_extrude` (the core cases)
  - `create_plane` offset
  - `sketch_offset` and `convert_entities`
  - `edit_feature` depth edits
  - `check_errors`
  - `get_mass_properties`: volume deltas matched hand calculations on every cut, which made it the best verification signal
  - `insert_component` (the origin lands exactly) and `rotate_component`
  - `set_component_fixed` and `set_component_visibility`
  - `close_document`
  - `interference_detection`: it found a real 1 mm sketch error that bounding-box checks missed

The code pointers below come from a read-only pass (line numbers approximate). Every finding is a **field report and has not been reproduced in a test**, so confirm each with a minimal live probe before fixing.

## P1: silent wrong geometry or the most wasted calls

### 1. Sketch entities snap or shift; `draw_*` doesn't detect it
**Observed**
- When a `draw_line` started exactly at the previous line's end point, the new line's end moved by about 0.3–1.1 mm. For example, (-5, 3.5) became (-4.667, 3.5).
- Endpoints within about 0.6 mm of an existing sketch line, or of a model edge coplanar with the sketch plane, snapped onto it.
- Lines of about 0.2 mm failed with "SOLIDWORKS did not create a line".
- A polygon with 0.6 mm steps came out wrong: a 3.2 mm segment ended at Y 6.4 instead of 5.8.
- `draw_arc` snapped to nearby arc centres.
- All of this happened while the tools reported ok.

**Code**
- In `solidworks_mcp/sw_sketch.py`:
  - `draw_line` (l.235) calls `SketchManager.CreateLine`.
  - `draw_arc` (l.318) calls `CreateArc`.
  - `draw_rectangle` (l.296) and `draw_polygon` (l.383) work the same way.
- Nothing in the repo sets `AddToDB`, `DisplayWhenAdded`, inference or snapping.
- `_drawn()` (l.97) only checks that the segment count grew.

**Fix**
1. In `_require_open_sketch` (l.116) or a shared context manager:
   - set `SketchManager.AddToDB = True` and `DisplayWhenAdded = False`
   - restore both in a `finally` block
2. Also consider turning off the user preference for sketch inference/snap (`swSketchInference`, `swInputDimValOnCreate`, grid snap) for the call, and restoring it afterwards. Check that each toggle is in `tools/compat/sw2017_api_members.txt`.
3. After creation, read `GetStartPoint2` and `GetEndPoint2` (and the arc centre) of the returned segment.
   - If any coordinate differs from the request by more than 1e-6 m, return `ok:false` with the requested and actual values.
   - Optionally delete the bad segment.
4. Add a `draw_polyline(points, closed)` tool that creates every segment with AddToDB on and verifies each vertex. Agents wanted this most.

**Test**
- Unit: a fake `SketchManager` whose `CreateLine` returns a segment with shifted endpoints must produce `ok:false`.
- Live: draw a closed 10-point star and a polygon with 0.6 mm steps next to existing geometry, then compare every vertex.

### 2. Lines lost when an agent issued several `draw_line` calls in one message
**Observed:** lines went missing when several `draw_line` calls were sent in parallel from one client message.

**Code**
- `server.py` already serializes every call behind `COM_LOCK = asyncio.Lock()`, so this is probably **not a COM race**.
- The more likely cause is #1: lines whose endpoints coincide merging, or failing to be created, under inference.

**Fix:** none beyond #1. Re-test after #1. If it persists, log the order of calls.

**Note:** the lock is per call, not per workflow. A second client can interleave calls between yours. That is fine for now, but worth knowing.

### 3. The active document switches between calls, and results don't say which document they used
**Observed**
- In the middle of a sequence, the active document became another open part or the assembly.
- In one batch, `list_features` and `get_bounding_box` answered from different documents.

**Code**
- `active_document()` in `sw_core.py:627` returns `ActiveDoc`, re-read on every call.
- `result()` in `sw_core.py:218` doesn't include the document title.
- The only way to switch documents is `open_document` (`sw_file.py:263`), which always calls `ActivateDoc3`.

**Fix**
- Add `active_document: <title>` to `result()` or `feature_result` (`sw_core.py:1633`) for every tool that touches a document.
- Add an `activate_document(title)` tool built on `ActivateDoc3`.
- Optional: a `document` argument on mutating tools that activates the named document first and fails if the switch doesn't happen.
- Investigate what flips the active document. Suspects:
  - `insert_component` re-activation (there was a fix for this in Phase 5)
  - `interference_detection`
  - `open_document` of an assembly's parts

**Test (live):** open 3 parts and an assembly, run a sequence of tools, and assert that `active_document` stays stable unless switched.

### 4. `linear_pattern` reports success when it creates no instances
**Observed:** with an edge direction, the pattern feature was created but added no geometry. It needed `reverse1=true` to go toward +X, yet it returned ok.

**Code**
- `sw_feature.py:924` calls `FeatureLinearPattern5`, falling back to `FeatureLinearPattern4`.
- `reverse1` and `reverse2` are passed straight through.
- Success means "feature returned and `whats_wrong` is empty".

**Fix**
- Record body volume and face count, or the body count, before and after. If nothing changed, return `ok:false` with the hint "direction may point off the body; try reverse".
- Return the resolved direction as a model-space vector, from the edge's or axis's direction and the reverse flag.

**Test (live):** a seed cut near the +X end, patterned toward +X, must be reported as a failure.

### 5. The cut and boss direction conventions differ, and the auto-reverse is partial
**Observed**
- On a +Z-facing sketch plane:
  - a cut with default settings goes −Z, and `reverse=true` goes +Z
  - a boss with default settings goes +Z
- `create_plane flip=true` places the plane at −Z.
- A cut aimed the wrong way succeeds silently whenever there is material on both sides.

**Code**
- `boss_extrude` is at `sw_feature.py:344` (`FeatureExtrusion3`) and `cut_extrude` at l.396 (`FeatureCut4`/`FeatureCut3`). The flip and reverse plan is `_ExtrudePlan.head` (~l.300).
- The cut's auto-reverse (~l.430) retries only when the first attempt returns `None`.

**Fix**
- Add `direction: "+normal" | "-normal"` with the same meaning for boss and cut. Map it to the right flag for each feature type.
- Report the extrusion direction in model coordinates, from the sketch-plane normal and the flag.
- Report the volume delta.
- Document the convention in both tool descriptions.

**Test:** unit-test the mapping. Live: on Front Plane, a boss with `+normal` and a cut with `+normal` both act toward +Z.

## P2: wrong or misleading readbacks

### 6. `get_bounding_box` is about 1 mm loose around arcs
**Observed:** a 240 mm part with R16 corners read ±121, and an agent spent a run chasing a defect that didn't exist.

**Code:** `sw_inspect.py:~203` uses `GetPartBox(True)` for parts and `GetBox(0)` for everything else, and both are loose.

**Fix**
- Build a tight box from `IBody2.GetExtremePoint(±1,0,0)`, `(0,±1,0)` and `(0,0,±1)` per body (`iter_body_context` exists), and take the union.
- Return `tight: true`.
- Keep the loose box as a fallback, with `tight: false`.
- Check `GetExtremePoint` against the compat list.

**Test (live):** a 240×70 R16 extrude must read exactly ±120.

### 7. `list_sketch_segments` names the wrong sketch while one is being edited
**Code:** `enumerate_sketch_segments` (`sw_core.py:1193`) labels an unnamed open sketch with `latest_sketch(doc)`, the newest ProfileFeature. That label is wrong after `edit_sketch` on an older sketch. `create_sketch` and `close_sketch` use the same shortcut.

**Fix**
- Resolve the open `ISketch` against each sketch feature's `GetSpecificFeature2`, or track the name when `edit_sketch` and `create_sketch` run.
- Add a regression test.

### 8. `delete_feature` deleted a different, empty sketch than the renamed one requested
**Code**
- `sw_feature.py:1039` runs `find_feature(doc, name)`, then `Select2(True, 0)`, then `DeleteSelection2(0)`.
- `Select2(True, …)` **appends** to the existing selection, so anything already selected, such as a sketch left selected by a previous tool, gets deleted too.

**Fix**
- Clear the selection first (`ClearSelection2(True)`), then `Select2(False, 0)`.
- Verify afterwards that the named feature is gone and that the feature count fell by exactly the expected amount.
- Return the deleted names and types.
- Check how `find_feature` matches renamed sketches: exact `Name` versus a localized or type match.

### 9. `set_feature_suppression` neither reports nor checks suppression state
**Observed**
- On a child feature the call silently skipped: the `changed` list came back shorter than requested.
- On an already-suppressed feature it returned `ok:false`.

**Code:** `sw_feature.py:1087` runs `Select2(False, 0)` then `EditSuppress2` or `EditUnsuppress2`. It never reads `IsSuppressed2` or `GetSuppression`.

**Fix**
- Read the state before and after the call.
- If the feature was already in the target state, return ok with `already: true`.
- Report the children that were suppressed as a side effect.
- Fail only when the final state doesn't match the target.

### 10. `rebuild_document` returns `ok:false` with an empty problems list
**Code**
- `sw_file.py:692` sets `ok = rebuilt and not problems`.
- `rebuild()` (`sw_core.py:667`) returns False on **any exception** from `EditRebuild3`.
- Warnings count as problems because `whats_wrong` (`sw_core.py:1610`) doesn't filter `is_warning`.

**Fix**
- Return the exception text and the raw return value.
- Treat warnings separately, as `warnings: [...]`, and don't fail on them.
- If the problems list is empty and `ForceRebuild3` succeeds, return ok.

## P3: sketch editing ergonomics

### 11. `sketch_fillet` indices shift and it can't select by point
**Code**
- `sw_sketch.py:480` selects segments by index from `GetSketchSegments()` order, then calls `SketchFillet2`.
- That order is SOLIDWORKS-internal: each new fillet arc is inserted, so the indices of lines shift by 1.
- A wrong guess fillets the same corner twice and leaves duplicate arcs.
- Selecting by vertex coordinates fails with "Nothing of type VERTEX was found".

**Fix**
- Accept `corners: [{x_mm, y_mm}]`. Resolve each to its two adjacent segments server-side, by matching endpoints within a tolerance, and fillet one corner at a time.
- Return the updated segment list.
- Reject a corner that already has a fillet arc.

### 12. `sketch_offset` leaves the original chain
**Code:** `sw_sketch.py:587` calls only `SketchOffset2`.

**Fix:** add `construct_original: bool`. When set, flag the source segments with `ConstructionGeometry = True`; agents needed this every time.

### 13. `add_dimension` moves the line's end point, never its start
**Code:** `sw_sketch.py:812` calls `AddDimension2`, then `SetSystemValue3`, and the solver chooses which end moves.

**Fix**
- Add `anchor: "start" | "end"`. Temporarily add a `Fixed` relation to the anchor point, set the value, then remove the temporary relation.
- Document the behaviour.

### 14. `undo` reports "refused" inside an open sketch
**Code:** `sw_select.py:61` judges success by the feature-name list before and after. Inside a sketch the feature list doesn't change, so the result is `ok:false`.

**Fix:** when `ActiveSketch` is set, compare the sketch segment and point counts (`_segment_count`) instead.

### 15. `create_sketch` doesn't report how sketch axes map to model axes
**Observed**
- In a default-template part, the planes map as follows:
  - Front Plane: sketch x → X, y → Y.
  - Top Plane: sketch y → −Z.
  - Right Plane: sketch x → −Z, y → Y.
- Agents had to rediscover this three times.

**Code:** `sw_sketch.py:139` returns only the name and the target.

**Fix:** return `sketch_x_axis`, `sketch_y_axis` and `normal` as model vectors, plus `origin`, from `ISketch.ModelToSketchTransform` (inverse). The same applies to `edit_sketch`.

## P4: failures with no detail

### 16. `loft` fails with only "SOLIDWORKS did not create the loft"
**Repro**
- Two rounded rectangles on parallel planes 2.8 mm apart: 240×70 R16 lofted to 234.4×70 R16 (narrower, same height and corner radius).
- It failed with merge on or off, on a plane or a face, and with 3 or 4 profiles.
- 234.4×70 R16 lofted to 232×67.6 R14.8 worked, and so did identical profiles.

**Code:** `sw_feature.py:872` calls `InsertProtrusionBlend2` (or `InsertCutBlend`) and selects the profiles via `SelectByID2` with mark 1. It has no start-point or connector control and no guide curves.

**Fix**
- The most likely cause is a twist or start-point mismatch: the profiles' first segments don't correspond, and the rounded rectangles have differently-ordered segments.
- Options:
  - Select each profile with a point pick at a matching corner. With `SelectByID2`, the pick point picks the start vertex.
  - Expose a `start_points` argument.
- Surface `whats_wrong` and the feature-error code (`GetErrorCode2` on a failed feature, if one exists).

**Test (live):** reproduce the 240 → 234.4 case and make it pass.

### 17. Fillet options
**Observed**
- `fillet_variant type=variable` on the 8 edges of a rounded-rectangle face perimeter returned a generic failure.
- `fillet` with `propagate=false` on the end edges still produced an R4 that tangent-propagated onto adjacent edges that had just been filleted R1.2. The result matched a uniform R4 to four decimals.

**Code**
- `fillet` (`sw_feature.py:543`) calls `FeatureFillet3(UNIFORM_RADIUS | [PROPAGATE], r, …)`, so the bit is omitted when `propagate` is false. SOLIDWORKS may still propagate along tangent chains because of the `swFeatureFilletPropagate` / tangent-propagation option. Check that `swFeatureFilletOptions` has no other propagate bit for 2017, and test with `FeatureFillet3` options 0.
- `fillet_variant` (l.1439) passes only `[r_start, r_end]` in Radii. A variable fillet across 8 edges needs per-vertex radii, one per vertex of the edge chain. That is why it fails on chains.

**Fix**
- Variable: build the Radii array per vertex (or reject chains of more than 1 edge with a clear message), and support `vertex_radii`.
- Constant: verify the propagate behaviour live, and document whether tangent propagation can be disabled on 2017.

## P5: output size and missing options

### 18. `list_faces` / `list_edges` can overflow the client's token limit
**Code:** `sw_inspect.py:~87, ~137` has type, area/length and normal filters but no limit.

**Fix:** add `limit`/`offset`, `feature` (faces of a named feature) and `within_box` filters. Default `limit` to 200 and return `truncated: true`.

### 19. `capture_screenshot` can't keep the file
**Code:** `sw_inspect.py:~422` writes `OUTPUT_ROOT/screenshots/capture_<ts>.png`, resizes it, **deletes it**, and returns base64 only.

**Fix:** add an optional `save_as` argument (a file name under `OUTPUT_ROOT/screenshots/`), keep the file, and return its path.

### 20. Tools the agents asked for
- `activate_document` (see #3)
- `draw_polyline` (see #1)
- tight per-body bounding box (see #6)
- section-view capture: a temporary section plane, or `capture_screenshot` with a `hide_components` list (agents hid components by hand)
- a regular-star helper (optional)

### 21. Saving project files outside `OUTPUT_ROOT`
**Observed**
- Correctly refused per ADR-0005: `sw_file.py:79`, `:868`.
- As a result, a project that keeps its CAD in its own repo has to copy the files into `sandbox/` and back.

**Fix:** document that workflow in `docs/clients.md`. Optionally support several allowed roots through `SW_MCP_OUTPUT_ROOT` (a list), still refusing everything else.

## Rulebook candidates (Phase 6, ADR-0004)
- **Shared frame:** for multi-part products, model every part in place in one frame and insert everything at the origin. Mirrored copies come from `rotate_component`.
- **Verify by measurement:** check every feature with a volume delta against a hand calculation, a tight bounding box and `check_errors`. "No exception" is not proof.
- **Sketching:** prefer `draw_rectangle`, `draw_polygon` or (after #1) `draw_polyline`. Check `list_sketch_segments` against the intended coordinates.
- **Serial calls:** issue geometry calls serially, and re-check the active document after any open or switch until #3 lands.
- **Acceptance gate for an assembly:** `interference_detection` reports 0.
- **Fallbacks:** if a loft or variable fillet fails twice, fall back to extrude + cut or a uniform fillet, and record the deviation.
- **Briefing subagents:** give them a fully resolved numeric spec plus the current known-quirks list.

## Tests and compat (where to add coverage)
- **Offline tests:** `tests/test_sw_core.py` and `tests/test_sw2017_*.py` (api_compat, enums, fixes, phase4, phase5_tools, batchA/B/C files).
- **Fakes:** there is no shared fake SW. Each file defines its own (`FakeDispatch`/`FakeBody` in `test_sw_core.py`, `FakeApp` in `test_sw2017_fixes.py`, `Harness` in `test_sw2017_batchC_edit.py`). A small shared fake `SketchManager` and segment would help #1, #11 and #14.
- **Live tests:** `tests/live_*.py`. Live work is strictly serial, one small stage per agent.
- **Compat list:**
  - Every new SW member must be in `tools/compat/sw2017_api_members.txt`, which `tools/compat/dump_sw_tlb.py` generates.
  - Members that aren't in the typelib go in `compat_allowlist.txt`.
  - Enum values are in `sw2017_enums.txt`.
- **New members likely needed:**
  - `ISketchManager.AddToDB`
  - `ISketchManager.DisplayWhenAdded`
  - `IBody2.GetExtremePoint`
  - `ISketch.ModelToSketchTransform`
  - `IFeature.IsSuppressed2` / `GetSuppression2`
  - `IModelDoc2.ClearSelection2`
  - `ISketchSegment.ConstructionGeometry`

## Waiting on Zach
- **Fix order:** recommend #1 (snapping plus endpoint verification), then #3 (active document), #4 and #5 (silent pattern and cut results), #6 (tight bounding box) and #8 (delete selection append). Those caused the silent wrong geometry and most of the wasted calls.
- **Guided session:** recommend counting this field use as the 5.4 guided session for 🧑 G5.

## Next steps (in order)
1. Reproduce #1, #3, #4, #6 and #8 with minimal live probes. Record pass/fail in `docs/reports/phase5-field-findings.md`.
2. Implement the fixes in the recommended order. Each fix gets an offline unit test with fakes and a live probe. Implementer and verifier are different agents.
3. Then handle #5, #7, #9, #10, #11–#15, #16–#17 and #18–#21. Triage whatever is left into PLAN.md Phase 7.
4. Seed the Phase 6 rulebook with the candidates above.

## Gotchas learned
- Clients driven from another project still write to this MCP's `OUTPUT_ROOT` (`sandbox/`). Keep project files out of this repo, because `sandbox/` is scratch only.
- `get_bounding_box` looseness caused a false alarm. Until #6 is fixed, use volume and specific vertices for verification.
