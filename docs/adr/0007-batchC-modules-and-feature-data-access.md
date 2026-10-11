# ADR-0007: Batch C tool modules and feature-data access

**Status:** Accepted (2026-10-11, G-C0)

## Context
Batch C adds about 17 tools across assemblies, sheet metal, threads, surfaces and a generic `edit_feature`. Two problems shape how that work is done:

1. **File conflicts.** ADR-0003 wants offline work in parallel. Today every tool family touches the same three shared places:
   - `server.py`, to register the module
   - `sw_core.flag_methods`, the central method-name lists for late binding
   - `sw2017_fences.py`

   Parallel subagents editing these would conflict.
2. **Insert members are missing in 2017.** Several of them are ❌ in 2017, for example `InsertLinearComponentPattern`, a sketched-bend insert and `FeatureRevolveSurface`. Several that are ✅ are silent no-ops. The `CreateDefinition` / `IFeature.GetDefinition` / `ModifyDefinition` path, with typed `I*FeatureData` interfaces (most are ✅), is an alternative route, and the only route for editing existing features.

## Decision
1. **New tool families go in new modules:** `sw_mates_adv`, `sw_asm_pattern`, `sw_sheetmetal`, `sw_thread`, `sw_surface`, `sw_edit`. A single serial C0 step registers all of them in `server.py` up front.
2. **Per-module late-binding flags.** `sw_core` gains `register_flag_methods(interface, names)`. Each module declares, at import time, the member names it calls with arguments. The central lists stay as they are for upstream code, which keeps the upstream merge easy.
3. **Shared files after C0 are orchestrator-only:** `server.py`, `sw_core.py`, `sw2017_fences.py` and `docs/FORK_CHANGES.md`.
4. **Feature-data access has one guarded helper,** `feature_data(feature, doc)`, a context manager:
   - `GetDefinition`, then `AccessSelections(doc, None)`
   - the caller's edits
   - `ModifyDefinition`
   - `ReleaseSelectionAccess` in a `finally`, so SW is never left in an edit state.

   It returns `changed` only when a read-back after the rebuild shows the new value.
5. **`edit_feature` is allow-listed.** v1 covers Extrude (depth, reverse), Fillet (radius), Chamfer (distance), LinearPattern (spacing, count), CircularPattern (count, angle) and Shell (thickness). Other type names are refused with the type listed. Each addition needs a live round-trip test.

## Consequences
- C1, C2 and C3 can be built in parallel with no merge conflicts.
- There are 6 more fork-owned files. Upstream diffs stay small.
- One audited place handles the selection-access lifecycle, which is the main hang risk in feature-data editing.
- `edit_feature` grows deliberately rather than claiming to edit anything.
