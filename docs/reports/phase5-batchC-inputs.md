# Phase 5 Batch C: inputs for the planner (offline read, no code changed)

Sources: newest handoff `docs/handoff/2026-10-10-01-phase5-t5-restart.md` (T5 state; Batch C not mentioned), `docs/reports/phase5-gap-analysis.md`, `phase5-batchA-live.md`, `phase5-batchB-live.md`, `docs/adr/0001-0006`, `rules/candidates.md`, `solidworks_mcp/`.

## 1. 2017 lessons from Batch A/B

**Silently no-op or inert APIs (return OK/void, change nothing)**
- `IAssemblyDoc.EditMate4`: right 16-arg order, but no-op; `edit_mate` re-creates the mate from entity refs (batchA-live.md:13, :25).
- `EditRedo` / `EditRedo2`: restore nothing after API changes; `redo` fenced (batchA-live.md:20).
- `EditUndo2` returns void; judge success by feature-tree count. One feature can need several undo steps (batchA-live.md:20).
- `IMassProperty.OverrideMass`: sets only `UserAssigned`; `Mass` unchanged (batchB-live.md:12).
- `IFeatureManager.InsertCombineFeature` and `IPartDoc.InsertCombineFeature`: return Nothing for all arg forms (batchB-live.md:11).
- `PreSplitBody2` works (2 temp bodies) but `PostSplitBody` builds nothing (batchB-live.md:13).
- `FeatureFillet3` type 3 (full round) builds a plain edge fillet (batchB-live.md:14).
- `InsertCosmeticThread3`: unknown standard strings silently fall back to '2-4.5'; use standard 2 = ISO 'Machine threads' (batchB-live.md:88).
- Hole Wizard tapped hole with Value6 = 0 builds a 2 in thread (batchB-live.md:17).
- `IBody2.Select4` selects the wrong body or is refused; select by name via `SelectByID2(name, "SOLIDBODY")` (batchB-live.md:18, batchA-live.md:19). `IBody2.Save` takes an IStream; use select + `SaveAs` (batchA-live.md:23).
- 3MF `SaveAs` returns False/error 1 but writes a valid zip (gap-analysis.md:11).
- `insert_component(configuration=...)`: option 2 fails; use 0 then set `ReferencedConfiguration` (batchA-live.md:27).
- Config switch leaves geometry stale until rebuild (batchB-live.md:19).

**Selection mark conventions (all verified live)**
- Width mate (`AddMate5`): width faces mark 1, tab faces mark 16 (tool maps user mark 2 to 16) (batchA-live.md:26; `sw_assembly.py:507,564-567`).
- Second-direction end target: mark 2 (batchA-live.md:11).
- Dome face 1; move/copy body 1; mirror body 256 (upstream `mirror_feature(mirror_body)` still uses 1, untested); wrap sketch 4 / face 1; face-fillet set 2 = mark 4 (batchB-live.md:20, :115).

**Modal-dialog risks**
- Equation/global variable deleted while a dimension still used it, then save: blocking "Rebuild?" modal. Fixed by `prepare_for_save` (`sw_file.py:121`) plus `delete_equation` guard (batchB-live.md:8).
- `dialogs_suppressed()` (`sw_core.py:522`) turns off user-pref toggles 10 and 77 (`FEATURE_DIALOG_TOGGLES`, `sw_core.py:518`) and restores them; an erroring feature returned cleanly with no dialog (batchA-live.md:31). `dimension_dialog_suppressed` at `sw_core.py:497`.
- Bad input can surface a raw COM exception (-2147417851) instead of a clean message (batchB-live.md:101).
- R3 watchdog (timeout + dialog caption detect) is still unbuilt.

**Current fences** (`solidworks_mcp/sw2017_fences.py:30-55`, mechanism per ADR-0006; `SW_MCP_DISABLE_FENCES=1` re-probes): `auto_dimension_view`, `combine_bodies`, `split_body`, `set_mass_override`, `redo`. `fillet_variant type=full_round` is refused inside the tool, not in FENCES. An unknown fence name raises KeyError at startup.

## 2. Batch C gap analysis summary (gap-analysis.md:133-135, plus table rows)
Planned Batch C:
- A4 advanced mates (gear, rack_pinion, screw, hinge, universal, cam, path, limit_distance/angle) via `AddMate5` extra args; L.
- A10 component patterns (`InsertDerivedPattern(2)`, `MirrorComponents3`; linear/circular via `FeatureLinearPattern5`/`FeatureCircularPattern5` with component selection); L.
- A17 assembly features (`InsertJoin2`, `InsertCavity4`); L.
- P2 design tables (Excel needed; defer).
- P6 sheet metal suite; L.
- P8 modeled threads and helix (`InsertHelix`, `InsertVariablePitchHelix`); L.
- P10 dome and P11 wrap: already done in Batch B.
- P12 curves (M-L), P16 section properties (M), P19 surfacing (L).
- P20 generic `edit_feature` via `GetDefinition`/`ModifyDefinition` (L; typed data interfaces mostly absent, late-bind).
- R3 dialog watchdog, R5 persistent refs, shell multi-thickness (`InsertMultiThickness` absent), sweep/loft guide curves (`InsertProtrusionSwept4`, `InsertProtrusionBlend2`).
- Also deferred: A12 exploded views (could be C), A7 `create_subassembly` (not implemented/tested in A, batchA-live.md:32).
- Risks: absent typed interfaces need live probes before coding; optional components (Excel, eDrawings) must degrade cleanly.

## 3. Member presence (tools/compat/sw2017_api_members.txt)
PRESENT unless marked ABSENT.
- Mates: `IAssemblyDoc.AddMate`, `AddMate2`, `AddMate3`, `AddMate4`, `AddMate5`; `EditMate` to `EditMate4`. ABSENT: `IAssemblyDoc.CreateMateData`, `IModelDocExtension.InsertMate*`/`CreateMate*`, `IFeatureManager.CreateMateFeature`, `IMateFeatureData`. Only `IFeatureManager.InsertMateReference`/`2` exist. `IMate2`: Alignment, CanBeFlipped, DisplayDimension(2), Flipped, GetMateEntityCount, MateEntity, Max/MinimumVariation, Type.
- Patterns (IFeatureManager): `FeatureLinearPattern`, `2`, `3`, `4`, `5`; `FeatureCircularPattern`, `2`..`5`; `FeatureFillPattern`; `FeatureSketchDrivenPattern`; `FeatureLocalCurveDrivenPattern`; `InsertDerivedPattern`, `2`; `InsertTableDrivenPattern`, `2`. ABSENT: `InsertLocalLinearPattern`, `InsertLinearComponentPattern`, `InsertCircularComponentPattern`.
- Generic: `IFeatureManager.CreateFeature`, `CreateDefinition`; `IFeature.GetDefinition`, `ModifyDefinition`, `GetTypeName`, `GetTypeName2`.
- Assembly: `MakeAssemblyFromSelectedComponents`, `InsertNewVirtualAssembly`, `InsertNewVirtualPart`, `MirrorComponents`, `2`, `3`, `InsertDerivedPattern`, `DissolveComponentPattern`, `DissolveSubAssembly`, `ReplaceComponents`, `2`; explode: `CreateExplodedView`, `ShowExploded2`, `AutoExplode`, `EditExplodeParameters`, `GetExplodedViewNames2`, `IConfiguration.AddExplodeStep`, `IsExploded`; `InsertCavity`..`InsertCavity4`, `InsertJoin`, `InsertJoin2` (interface owner not re-verified).
- Sheet metal, IFeatureManager: `InsertSheetMetalBaseFlange`, `2`; `InsertSheetMetalEdgeFlange`, `2`; `InsertSheetMetalMiterFlange`; `InsertSheetMetalHem`, `Hem2`; `InsertSheetMetal3dBend`; `InsertSheetMetalCornerTrim`; `InsertSheetMetalLoftedBend`, `2`; `InsertSheetMetalGussetFeature`, `2`, `3`; `InsertGussetFeature2`, `3`; `InsertConvertToSheetMetal`, `2`. IModelDoc2 only: `InsertSheetMetalFold`, `InsertSheetMetalUnfold`, `InsertSheetMetalJog`, `InsertSheetMetalBreakCorner`, `InsertSheetMetalClosedCorner`. IPartDoc: `InsertBends`, `InsertBends2`, `ExportFlatPatternView`, `ExportToDWG`, `ExportToDWG2`. ABSENT on IFeatureManager: `InsertSheetMetalFold/Unfold/Jog`.
- Thread/curves: `IFeatureManager.InsertCosmeticThread`, `2`, `3`; `IModelDoc2.InsertHelix`, `InsertDome`, `InsertCompositeCurve`, `Insert3DSplineCurve`, `InsertSplitLineProject`, `InsertSplitLineSil`; `IFeatureManager.InsertSplitLineIntersect`, `InsertWrapFeature`, `2`; `InsertVariablePitchHelix`. ABSENT: `IFeatureManager.InsertHelix`.
- Sweep/loft: `InsertProtrusionSwept`..`4`; `InsertCutSwept`..`5`; `InsertProtrusionBlend`, `2`; `InsertCutBlend`; `InsertSweepSurface`..`3`.
- Surfaces: `IFeatureManager.FeatureExtruRefSurface`, `2`, `3`; `InsertRevolvedRefSurface`; `InsertSewRefSurface`; `InsertUntrimSurface`; `PreTrimSurface`/`PostTrimSurface`; `InsertCutSurface`; `InsertFillSurface2`; `InsertMidSurface`; `InsertRuledSurfaceFromEdge2`; `FeatureBossThicken`, `FeatureCutThicken`. IModelDoc2 only: `InsertLoftRefSurface`, `2`; `InsertOffsetSurface`; `InsertPlanarRefSurface`; `InsertExtendSurface`; `InsertFeatureReplaceFace`; `FeatureBossThicken2`, `FeatureCutThicken2`. ABSENT: `FeatureRevolveSurface`, `InsertTrimSurface`, `InsertSplitBody`, `InsertBoundaryBoss`.
- Fillet: `IFeatureManager.FeatureFillet`, `2`, `3`; `IModelDoc2.FeatureFillet`..`5`; `FilletXpertChange/MakeCorner/Remove`; `InsertFeatureChamfer`.
- Split/combine: `PreSplitBody`, `PreSplitBody2`, `PostSplitBody`, `InsertCombineFeature` (present but inert, fenced), `InsertDeleteBody(2)`, `InsertMoveCopyBody(2)`.
- `IMassProperty`: `OverrideMass`, `SetOverrideMassValue`, `AddBodies`, `SetCoordinateSystem`, `UserAssigned` present (OverrideMass inert).
- Design tables: `IModelDoc2.InsertFamilyTableNew/Edit/Open`, `GetDesignTable`, `DeleteDesignTable`. ABSENT: `IModelDocExtension.InsertDesignTable`.
- Persistent refs: `IModelDocExtension.GetPersistReference3`, `GetObjectByPersistReference3`.

## 4. Code layout (package `solidworks_mcp/`)
- Registration: `server.py:55-65` imports modules; `@tool(...)` decorator at `sw_core.py:187`; fences applied afterwards via `apply_fences`.
- Mates/assembly tools: `sw_assembly.py` (16 tools; `add_mate` at :532, spec resolution :456-497, mark mapping :564-567). `MATE_TYPES` `sw_core.py:116`, `MATE_ALIGNMENTS` :123.
- Features (extrude, revolve, sweep :791, loft :850, linear_pattern :901, mirror_feature :993, hole_wizard :1187, cosmetic_thread :1275, fillets, dome): `sw_feature.py` (21 tools). Pattern call tries `FeatureLinearPattern5` then `4` with args[:20] (`sw_feature.py:939-943`).
- Other families: `sw_body.py` (move/copy, mirror/split/combine body), `sw_docdata.py` (configs, equations, properties, mass), `sw_inspect.py` (list_*, measure, mass), `sw_refgeom.py` (plane, axis, point, CS), `sw_select.py`, `sw_sketch.py`, `sw_file.py` (save/open/close, `prepare_for_save` :121), `sw_export.py` (helpers, no @tool), `sw_drawing.py`. No sheet-metal or surface module exists: new tools need new files (register in `server.py`) or go in `sw_feature.py`.
- Helpers in `sw_core.py`: `flag_methods` :304 (flags one name at a time; manager method lists :343-385), `call_versioned` :404, `safe` :430, `nothing` :437, `double_array` :446, `dispatch_array` :455, `byref_long` :459, `dimension_dialog_suppressed` :497, `dialogs_suppressed` :522, `require_part` :565.
- Tests (`tests/`): offline `test_sw2017_batch{A,B}_*.py` using `FakeFM`/`FakeDoc`/`Harness` (record COM calls; `test_sw2017_batchB_geometry.py:24-60`) with ConstantTests, RegistrationTests, per-tool classes; `test_sw2017_api_compat.py` checks every called member against the snapshot; `test_sw2017_enums.py`; fence tests. Live scripts `tests/live_p5_batchA.py`, `live_p5_batchB.py` (stage args, in-process handlers, `SW_MCP_OUTPUT_ROOT=sandbox`, logs in `sandbox/phase5/batchX/`, close only own docs). 227 unit tests at end of Batch A.
- Snapshot `tools/compat/sw2017_api_members.txt` (21006 lines, `Interface.Member`) has no enum values; confirm enums against the typelib.

## 5. Rules (rules/candidates.md:71-81, status proposed)
**R-010: Check `output_root` before building.** Enforcement: soft. Applies to: all. Rule: Call `solidworks_status` first and confirm `output_root` is the approved sandbox before building anything that will be saved. If it is not, stop and tell Zach rather than saving elsewhere. Why: Phase 5 T5: the Claude Code registration had no `SW_MCP_OUTPUT_ROOT`, so the finished part could not be saved. It was found only at the end. (proposed, 2026-10-10)

**R-011: Re-list faces before every selection.** Enforcement: soft. Applies to: part. Rule: Face indices and body names change after each feature. Re-run `list_faces` with a filter (normal, area, point) immediately before every face selection. Never reuse an index from an earlier listing. Why: Phase 5 T5: indices moved after the cut, and the body was renamed "CenterHole". (proposed, 2026-10-10)

## ADRs (decisions only)
0001 fork upstream (accepted); 0002 compat is API availability, every call must be in snapshot (accepted); 0003 orchestrator + Sonnet subagents + human gates (accepted); 0004 server-delivered modeling rules, selective hard gates (proposed); 0005 live testing only in `sandbox/`, attach-only (accepted); 0006 fence unfixable tools in `sw2017_fences.py`, listed with a reason, never touch COM (accepted).
