# Handoff: 2026-10-13-02 G5 passed and Phase 5 merged; Phase 6 (rulebook v0) next

## Resume prompt (paste into a fresh session)
`Read CLAUDE.md, then docs/handoff/2026-10-13-02-g5-passed-phase6-next.md, then continue from "Next steps".`

## Where we are
- **Phase / gate:** Phase 5 is ✅ (🧪 T5 ✅, 🧑 G5 ✅ on 2026-10-13). Phase 6 starts next and works toward 🧪 T6.
- **Branch:** `main`. `phase-5-clients-guided` was merged into it as `3a697d8` (no-ff). The working tree is clean apart from this file. Nothing has been pushed.
- **SOLIDWORKS:** running with 0 documents open. No preferences were changed.

## Done this session
- **MCP-level smoke run** through the restarted server's real `mcp__solidworks__*` tools. All steps PASS. Evidence: `docs/reports/phase5-mcp-smoke-postfix.md`.
  - Polyline star: measured volume matched the shoelace calculation to 0.0000%.
  - Sketch edits: fillet, then `delete_sketch_segment` took the count from 8 to 7.
  - Loft: 45875.73 mm³ against 45876 expected.
  - `activate_document`: the active document read back correctly.
  - Cleanup: 0 documents open.
- **G5 decisions (Zach):**
  - The 2026-10-12 field use counts as the guided session (5.4).
  - R-012…R-018 are confirmed as soft rules. R-013 stays a hard-gate candidate.
  - The merge was approved.
- **Docs:** PLAN status updated. `rules/candidates.md` marks R-012…R-018 confirmed. `rules/CHANGELOG.md` logs them and backfills the missing R-009 row.
- **Tests:** 655 unit tests OK on `main` after the merge.

## Decisions made (and where recorded)
- **Where confirmed rules live:** they stay in `candidates.md`, marked confirmed, the same way R-009 was handled at G4. They become `active` in topic files only when the Phase 6 rulebook ships, which follows `rules/README.md` ("documentation only until Phase 6"). Recorded in `rules/CHANGELOG.md` and `docs/PLAN.md`.

## Waiting on Zach
- Nothing blocking.
- Optional: push `main` to `origin`. Never push tags (ADR-0001).

## Next steps (in order)
1. Read ADR-0004 and the Phase 6 section of `docs/PLAN.md`.
2. **Settle which rules seed v0.**
   - Confirmed so far: R-002 (G1), R-008 (G1), R-009 (G4), and R-012…R-018 (G5).
   - R-001 and R-003…R-007, R-010 and R-011 are still *proposed*.
   - Ask Zach at G6, or earlier if 6.4 needs the answer to start. *Recommend:* seed v0 from the confirmed rules, and present the proposed ones at G6 with a recommendation for each.
3. **Implementation work (6.1 to 6.3)** goes to Sonnet subagents. All of it is offline, so the agents can run in parallel:
   - 6.1: topic files under `rules/`
   - 6.2: `solidworks_mcp/sw_rules.py`, providing instructions, resources and prompts. The diff to upstream files is registration only, and it gets logged in `docs/FORK_CHANGES.md`.
   - 6.3: the `record_build_plan` gate behind `SW_MCP_REQUIRE_PLAN=1`
4. 🧪 T6 is checked by a different agent from the implementer. Then present 🧑 G6.

## Gotchas learned
- `close_document` refuses a dirty scratch document unless you pass `force=true`. This is intended.
- The newer gotchas in `docs/handoff/2026-10-13-01-field-fixes-done-g5-next.md` still apply: arc rotation direction, COM identity, SelectByID2 picks, AddToDB undo, and other clients driving SOLIDWORKS.

## Key files
- `docs/adr/` (ADR-0004)
- `docs/PLAN.md`
- `rules/README.md`, `rules/candidates.md`, `rules/CHANGELOG.md`
- `docs/reports/phase5-mcp-smoke-postfix.md`
