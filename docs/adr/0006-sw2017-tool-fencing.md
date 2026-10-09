# ADR-0006: Fencing tools that can't work on SOLIDWORKS 2017

- **Status:** Accepted (approach approved by Zach at 🧑 G3, 2026-10-08; fenced list confirmed at 🧑 G4)
- **Date:** 2026-10-08

## Context
Phase 3 found one tool with no working 2017 route: `auto_dimension_view` calls `IDrawingDoc.AutoDimension`, which is the sketch-level auto-dimension and adds nothing to a drawing view. Phase 4 needs a uniform way to say "this tool doesn't work here" so the AI stops trying it, without deleting upstream code (that would make `git merge upstream/main` painful) and without silently returning `ok: true`.

Behavior *substitutions* (e.g. mapping `chamfer` `equal_distance` to `angle_distance` 45°) are not fences: the tool still does the job. They are ordinary fixes, documented in the tool description and `docs/FORK_CHANGES.md`.

## Decision
- **One registry in a fork-owned module:** `solidworks_mcp/sw2017_fences.py` holds `FENCES: dict[str, str]` (tool name → reason) and `apply_fences(tools, handlers)`.
- **Applied once at server start**, after every tool module has registered, via a single call in `server.py`. Upstream tool modules are not edited for a fence.
- **A fenced tool stays listed**, so clients see why it's unavailable:
  - its description is prefixed with `NOT SUPPORTED ON SOLIDWORKS 2017: <reason>.`
  - its handler is replaced by one that returns `result(False, "Not supported on SOLIDWORKS 2017: <reason>", fenced=True)` and never touches COM.
- **Escape hatch:** `SW_MCP_DISABLE_FENCES=1` skips `apply_fences`, so a live test can re-probe a fenced tool (e.g. after an SP or a new route is found).
- **Every fence** has a unit test, a row in `docs/FORK_CHANGES.md`, and appears in the 🧑 G4 fenced list.

## Consequences
- Upstream merges stay easy: the fence list is data in our own file, plus a one-line hook in `server.py`.
- If upstream renames a fenced tool, `apply_fences` must fail loudly (unknown name → `KeyError` at start-up, caught by the unit tests) rather than silently un-fence.
- The live matrix reports fenced tools as `FENCED`, which counts as acceptable for 🧪 T4.

## Alternatives considered
- **Unregister the tool:** clients would never learn why it's missing, and the AI might try to fake the behavior with other tools.
- **Edit each handler with an early return:** spreads fork diffs across upstream files.
- **Runtime version check (`RevisionNumber` major < N):** the right shape if we ever support several SW versions; premature with only 2017 in scope.
