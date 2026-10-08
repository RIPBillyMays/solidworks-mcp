# Handoff: 2026-10-08-01 Setup and plan (stopped at 🧑 G1)

## Resume prompt (paste into a fresh session)
`Read CLAUDE.md, then docs/handoff/2026-10-08-01-setup-and-plan.md. I've answered the G1 questions below; continue from "Next steps".`

## Where we are
- **Phase / gate:** Phase 1 done, 🧪 T1 passed. **Waiting at 🧑 G1 (plan review).**
- **Branch / changes:** on `main`, nothing committed yet (commit policy is a G1 question). Untracked: `CLAUDE.md`, `docs/`, `rules/`, `tools/compat/`. Modified: `.gitignore` (+`sandbox/`).
- **SOLIDWORKS state:** not running, never touched this session.

## Done this session
- **Feasibility:**
  - SW 2017 SP05 (25.150.83) is installed.
  - `SldWorks.Application` → 2017 CLSID, so no registry work is needed (ADR-0002).
  - 8 candidate servers were statically scanned against the 2017 typelib; Slacker-LLC was chosen (ADR-0001).
- **Fork:** `RIPBillyMays/solidworks-mcp` (origin), with an `upstream` remote → Slacker-LLC.
- **Install (Sonnet implementer, verified by the orchestrator):** `.venv` with Python 3.12.13, mcp 1.30.0, pywin32 312, pillow 12.3.0. Evidence: `docs/reports/phase1-baseline.md`.
- **🧪 T1:** unit tests 24/24 OK; `tools/compat/mcp_smoke_client.py` reports 92 tools, protocol 2025-11-25, no server `instructions`.
- **2017 API snapshot plus scripts:** `tools/compat/` (`dump_sw_tlb.py`, `scan_api_compat.py`, `sw2017_api_members.txt`).
- **Docs:**
  - `CLAUDE.md`, `docs/PLAN.md`, `docs/adr/0001–0005` + `README.md`
  - `docs/how-it-works.md` (learning doc)
  - `docs/FORK_CHANGES.md`, `docs/handoff/TEMPLATE.md`
  - `rules/README.md`, `rules/candidates.md` (R-001…R-007, all proposed), `rules/CHANGELOG.md`
- **Tool catalog (Sonnet):** `docs/reference/tool-catalog.md`.
  - 92 tools: file 10, refgeom 3, sketch 28, feature 17, inspect 11, assembly 5, drawing 18; plus 2 demo tools.
  - 6 high-risk tools.
  - It found **3 real bugs, all verified by the orchestrator** and added to PLAN 2.5:
    - 9 broken local imports
    - template preference ids 1/2/3 should be 8/9/10
    - `IMeasure.Calculate` needs 1 argument in 2017

## Decisions made (and where recorded)
- Fork Slacker-LLC (ADR-0001)
- Compatibility = API availability, with a committed 2017 snapshot (ADR-0002)
- Orchestrator + Sonnet, gates, handoffs (ADR-0003)
- Live-testing safety and sandbox (ADR-0005)
- ADR-0004 (rulebook delivered by the server) is **Proposed**

## Waiting on Zach (G1)
1. Approve PLAN and ADR-0001/2/3/5. ADR-0004: approve, modify, or defer to G6. *Recommendation: approve the direction now, details at G6.*
2. Commit the Phase 1 work on `phase-1-setup` and merge to `main`? *Recommendation: yes.*
3. Is the fork under `RIPBillyMays` (not `itjustvibes`) OK?
4. Default units: mm or in?
5. Assembly strategy default: top-down, bottom-up, or AI proposes per project for approval? *Recommendation: propose per project, because it feeds R-002 and the plan template.*
6. Second AI client for Phase 5: Cursor, Codex CLI, Gemini CLI?
7. Real-file access after testing: read-only allowed, or sandbox-only until G6?

## Next steps (in order)
1. Apply Zach's G1 answers:
   - update ADR-0004 status
   - update R-002 in `rules/candidates.md` and the units rule
   - update PLAN.md Status
2. If approved: commit on `phase-1-setup` → merge to `main` → push `origin`. Never push tags.
3. Phase 2, offline and parallel-safe: brief a Sonnet implementer on PLAN tasks 2.1–2.4, then a separate Sonnet verifier (mutation check). 🧪 T2.
4. 🔁 Handoff before Phase 3 (live); G2 needs Zach at the machine with SW 2017 open.

## Gotchas learned
- The typelib registry key `19.0` is **hex**: `LoadRegTypeLib(guid, 0x19, 0)`.
- Upstream `.gitignore` ignores `HANDOFF.md` and `STATUS.md`, hence the dated filenames here.
- The server reports its version as `1.30.0`, which is the **mcp SDK** version, not the package's `0.1.0`. Don't use it for version checks.
- `publish-mcp.yml` publishes upstream's package on `v*` tags, so never push tags (ADR-0001).
- `python` on PATH is 3.14; always use `.venv\Scripts\python.exe`.
- **Upstream's 24 unit tests pass even though 9 tools have broken imports.** The tests don't reach function-level imports, so "tests green" ≠ "tools work". Phase 2 adds an import-coverage test.
- Read enum values straight from the 2017 swconst with `LoadRegTypeLib('{4687F359-55D0-4CD3-B6CF-2EB42C11F989}', 0x19, 0, 0)` → `GetVarDesc(v).value`.
- The upstream comment at `sw_inspect.py:283` ("Calculate takes no arguments") is wrong for 2017. Treat upstream comments about API shape as 2026-specific claims, not facts.
- `scan_api_compat.py` expects a *directory of repo directories* (it was built for the candidate survey). Phase 2's test replaces it for this repo.

## Key files
`CLAUDE.md` · `docs/PLAN.md` · `docs/adr/` · `docs/how-it-works.md` · `docs/reference/tool-catalog.md` · `docs/reports/phase1-baseline.md` · `rules/candidates.md` · `tools/compat/`
