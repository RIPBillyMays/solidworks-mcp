# Plan: AI control of SOLIDWORKS 2017 via MCP

**Legend:** 🧪 automated test gate (must pass) · 🧑 human gate (Zach decides) · 🔁 handoff point (fresh session)
**Roles:** orchestrator = main Claude session; implementers and verifiers = Sonnet subagents (ADR-0003)

## Status
| Phase | What | State | Gate |
|---|---|---|---|
| 0 | Feasibility research | ✅ done 2026-10-08 | — |
| 1 | Fork, install, offline baseline | ✅ done 2026-10-08 | 🧪 T1 ✅ · 🧑 G1 ✅ (2026-10-08) |
| 5a | Client registration pulled forward (Claude Code, Claude Desktop, Codex CLI); see `docs/clients.md` | ✅ registered 2026-10-08 | 🧪 T5a: Codex ✅ · Claude Code ✅ · Claude Desktop ✅ (2026-10-08; Codex parked by Zach) |
| 2 | Static 2017 compatibility gate | ✅ done 2026-10-08 (merged to `main`) | 🧪 T2 ✅ (74 tests; `docs/reports/phase2-verification.md`) |
| 3 | Live smoke test on SW 2017 | ✅ done 2026-10-08 (merged to `main`) | 🧑 G2 ✅ · 🧪 T3 ✅ (`docs/reports/phase3-live-matrix.md`, `phase3-verification.md`) · 🧑 G3 ✅ Go (2026-10-08) |
| 4 | Fix or fence failing tools | ✅ done 2026-10-09 (merged to `main`; ADR-0006; fenced: `auto_dimension_view`) | 🧪 T4 ✅ (100 PASS, 1 FENCED, 2 UNVERIFIED; 102 unit tests) · 🧑 G4 ✅ (2026-10-09; R-009 confirmed; drawings deferred) |
| 5 | Connect AI clients + first guided session | ⏳ **next** (3D only) | 🧪 T5 · 🧑 G5 |
| 6 | Rulebook v0 ("the brain") | ⏳ | 🧪 T6 · 🧑 G6 |
| 7 | Hardening and upkeep | ⏳ | 🧑 G7 |
| ∞ | Rules learning loop | ongoing after G5 | per session |

## Goal and success criteria
1. Claude (Desktop and Code) plus at least one other MCP client can build a **part, an assembly and a drawing** *(drawings deferred by Zach at G4, 2026-10-09: focus on 3D modeling only)* in SOLIDWORKS 2017 from a natural-language request.
2. Every exposed tool is either **verified on 2017** or **fenced** (disabled with a clear reason).
3. A versioned **rulebook** governs how the AI plans and builds, and the server delivers it to any client (ADR-0004).
4. Regressions are caught by offline tests (unit tests plus the 2017 API compat check) and a repeatable live suite.

## Facts established (2026-10-08)
- **SOLIDWORKS:** 2017 SP05, rev 25.150.83, installed at `C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\`.
- **COM registration:** `SldWorks.Application` and `.25` resolve to the same CLSID, so no registry work is needed (ADR-0002).
- **Fork:** `RIPBillyMays/solidworks-mcp`, from upstream `Slacker-LLC/solidworks-mcp` (Apache-2.0).
- **Environment:** Python 3.12.13 venv. mcp 1.30.0, pywin32 312, pillow 12.3.0.
- **Server (T1 baseline):** 24/24 unit tests pass and 92 tools are listed over stdio. It sends no `instructions` at handshake.
- **Static scan:** every member the server calls exists in the 2017 typelib, except an unused `SaveAs3` in a flag list.

---

## Phase 1: Fork, install, offline baseline ✅
- [x] Fork and clone, `upstream` remote added
- [x] `.venv` (Python 3.12, uv) + editable install (subagent; verified by the orchestrator)
- [x] `tools/compat/mcp_smoke_client.py`: MCP handshake and tools/list with no SW running
- [x] `tools/compat/` 2017 API snapshot plus dump and scan scripts
- [x] CLAUDE.md, ADR-0001…0005, this plan, how-it-works explainer, rules scaffold, handoff template
- [x] `docs/reference/tool-catalog.md`: 92 tools (+2 demo) with side effects, risk and preconditions. 6 tools are high-risk: `open_document`, `save_document`, `save_active_document`, `export_document`, `add_dimension`, `capture_screenshot`.

🧪 **T1 (passed):** `unittest discover` passes 24/24, and the smoke client reports 92 tools with no SW running.

🧑 **G1: Plan review.** Zach decides:
1. Approve this plan and ADR-0001/2/3/5. Give ADR-0004 (rules approach) a direction: approve, modify, or defer to G6.
2. Commit policy: OK to commit the Phase 1 work on branch `phase-1-setup` and merge it to `main`?
3. The fork went to the active gh account `RIPBillyMays` (not `itjustvibes`). Is that right?
4. Answer the open questions at the bottom of this file (units, assembly default, second AI client).

🔁 Handoff after G1.

## Phase 2: Static 2017 compatibility gate (offline, no SW)
**Implementer (Sonnet) tasks:**
- **2.1 `tests/test_sw2017_api_compat.py`.** AST-parse `solidworks_mcp/*.py` and collect:
  - (a) PascalCase attribute calls
  - (b) string names in the `_*_METHODS` tuples and in `flag_methods(...)` / `value(obj, "X")` / `safe(obj, "X")` arguments

  Assert that each name exists in `tools/compat/sw2017_api_members.txt`. Use the interface-specific list where the receiver is known (`Extension` → `IModelDocExtension`, etc.) and any interface otherwise. Non-SW names go in `tools/compat/compat_allowlist.txt` with a one-line reason each.
- **2.2 Enum values.** Extend `dump_sw_tlb.py` to emit enum values (`swEndConditions_e.swEndCondBlind=0`) into `tools/compat/sw2017_enums.txt`. Add a test that the constants in `sw_core.py` (END_CONDITIONS, SURFACE_TYPES, CURVE_TYPES, fillet/chamfer/plane flags, `SW_INPUT_DIM_VAL_ON_CREATE`) match the 2017 values.
- **2.3** Remove `"SaveAs3"` from `_EXTENSION_METHODS` in `sw_core.py`. It's absent in 2017 and only produces a warning. Add the fork-modification header line and log the change in `docs/FORK_CHANGES.md`.
- **2.4** Run the upstream tool `tools/tlb_probe.py` against the installed 2017 typelibs and save its output to `docs/reports/phase2-tlb-probe.md`.
- **2.5 Confirmed upstream bugs.** Found by the tool catalog and verified by the orchestrator on 2026-10-08. Each fix gets a unit test:
  - **Broken local imports (9 sites).** `from sw_core import …` inside functions raises `ModuleNotFoundError` at call time when the server runs as a package. Affected:
    - `sw_assembly.py:196`
    - `sw_drawing.py:532,560,724,907`
    - `sw_file.py:305`
    - `sw_refgeom.py:136`
    - `sw_sketch.py:457,618`

    Fix: `from .sw_core import …`. Test: import-check every handler module's function-level imports.
  - **Template preference ids.** `new_document` passes 1/2/3, but `swDefaultTemplatePart/Assembly/Drawing` are **8/9/10** (verified in the 2017 swconst). Today it always falls back to disk discovery.
  - **`IMeasure.Calculate`** takes one parameter (`Entities`) in 2017. `sw_inspect.py:284` calls it with none. Fix: pass `nothing()`, which uses the current selection.
- **2.6 Unverified catalog claims.** The 2.2 enum test must confirm or refute: enum mismatches in revolve mid-plane, section/detail view options, drawing display mode and `DeleteSelection2`, plus possible silent no-ops `ViewDisplayShadedwithedges` and `TangentEdgeDisplay`. Dialog-raising preferences other than #10 (over-defining dimension prompt, STL/3MF export info) are checked live in Phase 3.

**Verifier (separate Sonnet):** re-run all offline tests, and confirm that the upstream diff is limited to 2.3 and that the test fails if a fake `SaveAs3(` call is injected (mutation check).

**Outcome (2026-10-08):**
- Upstream commits 10c2beb, 4831e37 and d07a29b were cherry-picked from `upstream/codex/continue-sw-compat` (denglobert, verified on SW 2016). They cover the 9-import part of 2.5 and add the `call_versioned` fallbacks.
- Implementer A did 2.3 and the rest of 2.5. Implementer B did 2.1, 2.2, 2.4 and 2.6. 2.6 confirmed 6 code bugs and refuted 1 claim (`DeleteSelection2(0)`); implementer C fixed all 6 from typelib values. Each fix carries a `# Phase 3: verify live` comment.
- The verifier passed T2: 74 tests, 0 expectedFailure, an empty allowlist, and all 4 mutations caught.
- Reports: `docs/reports/phase2-static-compat.md`, `phase2-tlb-probe.md`, `phase2-verification.md`.

🧪 **T2:** all offline tests are green (upstream's 24 plus the new compat tests), there are zero un-allowlisted misses, and the mutation check fails as expected.

Escalate to 🧑 only if an unfixable miss is found. 🔁 Handoff before Phase 3 (a live phase).

## Phase 3: Live smoke test on SW 2017 (serial, one agent at a time)
🧑 **G2: Live readiness checklist (Zach):**
- SOLIDWORKS 2017 is launched, the license is OK, and no dialogs are open.
- Own work is saved and closed.
- Tools > Options > Default Templates point at existing part, assembly and drawing templates.
- The sandbox path `C:\_Projects\solidworks-mcp\sandbox\` is OK.
- Zach is available to dismiss a dialog if a hang occurs.

The orchestrator then confirms attach: `solidworks_status` should report `25.150.x`.

**Tasks (one live implementer agent, serial):**
- **3.1** Run upstream `tests/live_p0_regression.py` and record the results.
- **3.2** Build `tests/live_sw2017_smoke.py`, ordered by the tool catalog's build-up sequence. Each step:
  - calls the tool **handler** (the same code path as MCP)
  - verifies by measurement, e.g. a 10×20×5 mm extrude gives volume 1000 mm³ ±0.1% and 1 body; fillet raises the face count; STEP export file exists and is >1 KB; a mate adds +1 mate; a drawing view adds +1 view
  - runs under a 60 s watchdog
- **3.3** Write the results to `docs/reports/phase3-live-matrix.md` (tool × PASS / FAIL / SILENT-FAIL / HANG × notes). Screenshots go in the sandbox run folder.

🧪 **T3 (core part workflow must PASS):** new part → sketch (rectangle, circle) → extrude → cut → fillet → mass properties → save to sandbox → STEP export.

🧑 **G3: Go/no-go.**
- **Go** if T3 passes.
- **No-go** if the core fails in ways that look structural. Then revisit ADR-0001 and run the same matrix on Fallback #1 (alisamsam) or #2 (HarrierPigeon).

🔁 Handoff.

## Phase 4: Fix or fence (iterative)
For each FAIL, SILENT-FAIL or HANG:
1. **Triage** into one of: missing API (use an older numbered variant) · enum value · late-binding marshalling · modal dialog · 2017 behavior bug · feature-type-name string difference.
2. **Implementer** fixes it, with a FakeDispatch unit test where possible, then does a serial live re-test of that tool only.
3. **Unfixable:** fence the tool. Write ADR-0006 (version fencing mechanism) the first time this happens. A fenced tool returns a clear "not supported on SOLIDWORKS 2017: <reason>" message.

🧪 **T4:** the full live matrix re-run shows every tool as PASS or FENCED, and the offline suite is green.
🧑 **G4:** Zach accepts the fenced list.
🔁 Handoff.

## Phase 5: Connect AI clients + first guided session
- **5.1 Claude Code:** `claude mcp add solidworks -- C:\_Projects\solidworks-mcp\.venv\Scripts\solidworks-mcp.exe` (user scope; decide project vs user at G5).
- **5.2 Claude Desktop:** add an entry in `%APPDATA%\Claude\claude_desktop_config.json`.
- **5.3** One more client of Zach's choice (Cursor, Codex CLI or Gemini CLI).
- **5.4 Guided session:** Zach asks for a simple part, and the orchestrator narrates each tool call and the COM call underneath it (learning goal; see `docs/how-it-works.md`).

🧪 **T5:** each client lists the tools and completes "50×30×10 mm block with a Ø10 mm through-hole, centered". Expected volume: 15000 − π·5²·10 ≈ 14214.6 mm³.
🧑 **G5:** Zach's hands-on review. Harvest the first rule candidates into `rules/candidates.md`.
🔁 Handoff.

## Phase 6: Rulebook v0, "the brain" (ADR-0004)
- **6.1** Rule file format and the `rules/` layout. Approve it in the G1 or G6 discussion.
- **6.2 New module `solidworks_mcp/sw_rules.py`.** It provides:
  - server `instructions`, generated from active rules
  - resources: `rules://index` and one per rule
  - prompts: `plan_part`, `plan_assembly`, `review_model`

  The upstream diff is registration only.
- **6.3 Hard gate:** a `record_build_plan` tool. While `SW_MCP_REQUIRE_PLAN=1`, modeling tools refuse until a plan is recorded. Inspection tools are never gated.
- **6.4** Seed rules from `rules/candidates.md` that Zach approved: plan-first, assembly strategy, fully-defined sketches, origin anchoring, naming, verify-after-feature.

🧪 **T6:**
- the smoke client sees the instructions, prompts and resources
- with the gate on, a modeling call without a plan is refused, and it succeeds once a plan is recorded
- a scripted scenario shows the model reading the rulebook before building

🧑 **G6:** Zach approves rulebook v0 and the enforcement level of each rule.
🔁 Handoff.

## Phase 7: Hardening and upkeep
- `SW_PROGID` environment variable (optional pin, ADR-0002).
- README section "SOLIDWORKS 2017 notes" with the compat table.
- CI: the compat tests run in `tests.yml`; delete or disable `publish-mcp.yml` in the fork (ADR-0001).
- **Upstream sync runbook:** `git fetch upstream` → merge on a branch → 🧪 T2 → live T3 subset → merge.
- Optional: offer generic fixes upstream as PRs (Zach decides each one).

🧑 **G7:** wrap-up review.

## Ongoing: rules learning loop
After every real modeling session:
1. **Retro (5 min):** what did the AI do wrong, slowly, or against Zach's intent?
2. Turn each finding into a `proposed` rule in `rules/candidates.md`, with an example of the mistake.
3. At the next gate, Zach approves or rejects each one. Approved rules become `active` and get an enforcement level (`soft` or `hard`).
4. Log every change in `rules/CHANGELOG.md`. Retire rules that stop earning their keep.

## Risk register
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A 2017 runtime behavior differs from 2026 (silent None, different type names) | High | Med | Phase 3 measures every result; Phase 4 fixes or fences |
| Modal dialog hangs COM | Med | High | Watchdog, serial live runs, Zach present at G2, dialog-suppression pattern |
| SW 2017 isn't officially supported on Windows 11 | Med | Med | Observe at G2; document any instability |
| A test touches real CAD files | Low | High | Sandbox-only I/O, close without saving (ADR-0005) |
| A user preference is left changed | Low | Med | Before/after recording of preferences in the live suite |
| An upstream merge reintroduces post-2017 calls | Med | Med | T2 compat test in CI |
| The model ignores soft rules | Med | Med | Promote rules to hard gates when retros show misses (ADR-0004) |
| Session context bloat | Med | Low | 🔁 handoffs at ~50%, at gates, and before live phases |

## G1 answers (Zach, 2026-10-08)
- **Commit:** yes. Phase 1 committed on `phase-1-setup` and merged to `main`.
- **Units:** **mm** by default → rule R-008.
- **Assembly strategy:** **the AI proposes per project** in its build plan and Zach approves → rule R-002.
- **AI clients:** **Claude** (Code + Desktop) and **Codex CLI**. Registration pulled forward as Phase 5a. The guided session (5.4) and full T5 stay after Phase 4.
- **Plan / ADRs:** plan accepted. ADR-0004 stays Proposed until G6.
- **Fork account:** `RIPBillyMays` is correct. Pushing to `origin` is approved.
- **Real-file access:** **sandbox-only** (R-007) until Zach says otherwise. The AI never opens or saves files outside `sandbox/`.

## ⚠️ Using the clients before Phases 2–4
The server is registered, but until Phase 2–4 fixes land, expect:
- **9 tools fail on call** (broken imports): `set_appearance`, `create_axis`, `draw_spline`, `sketch_mirror`, `list_mates`, section and detail views, `set_drawing_view`, and `insert_center_marks` with `selected_only`
- `measure` fails
- `create_new_document` picks a fallback template
- untested 2017 behavior everywhere else

Live use follows ADR-0005: Zach launches SW and saves his own work first.
