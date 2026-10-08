# SOLIDWORKS 2017 MCP: project instructions

Fork of [Slacker-LLC/solidworks-mcp](https://github.com/Slacker-LLC/solidworks-mcp) (Apache-2.0), adapted so Claude and other MCP clients can drive **SOLIDWORKS 2017 SP05 (rev 25.150.83)** on Zach's workstation.
- `origin` = `RIPBillyMays/solidworks-mcp` (our fork)
- `upstream` = `Slacker-LLC/solidworks-mcp`

## Start of every session
1. Read the **newest** file in `docs/handoff/` (filenames sort by date).
2. Read the **Status** table at the top of `docs/PLAN.md` to find the current phase and gate.
3. Don't re-litigate decided ADRs (`docs/adr/`). Read the relevant one before touching its area, and supersede it with a new ADR if a decision must change.

## Roles: orchestrator + Sonnet subagents (ADR-0003)
- **Main session = orchestrator.** It plans, writes and updates ADRs and the plan, scopes tasks, reviews diffs and reports, runs gates, and talks to Zach. It does not do bulk implementation itself.
- **Implementation and testing go to subagents with `model: "sonnet"`.** Every brief contains:
  - context
  - exact scope (which files may be created or modified)
  - acceptance criteria
  - explicit don'ts
  - "report back in ≤150 words; put long output in `docs/reports/`"
- **Implementer ≠ verifier.** A different subagent (or the orchestrator) checks the work against the acceptance criteria.
- **Offline work may run in parallel. Live-SOLIDWORKS work is strictly serial:** one agent at a time. There is a single SW instance, COM is single-threaded, and a modal dialog blocks everyone.
- The orchestrator reads reports, never subagent transcripts.

## Human gates
- Gates marked 🧑 in `docs/PLAN.md` need Zach. Stop and present:
  1. what was done
  2. test evidence
  3. the decisions needed, each with a recommendation
- Never pass a 🧑 gate on your own.
- 🧪 gates are automated and must pass before moving on. If one can't pass, escalate it as a 🧑 gate.

## Context budget and handoffs (Zach's standing instruction)
- **Write a handoff, then stop at a clean point**, when any of these happens:
  - context is around **50% full**
  - a 🧑 gate is reached
  - just before starting a live-SOLIDWORKS phase
- Write it to `docs/handoff/YYYY-MM-DD-NN-<slug>.md` from `docs/handoff/TEMPLATE.md`. Then give Zach the path and the one-line resume prompt.
- ⚠️ Upstream's `.gitignore` ignores any file named `HANDOFF.md` or `STATUS.md`. Never use those names.
- Stay lean:
  - delegate wide reading to subagents
  - ask for short reports
  - don't paste big files into the conversation

## SOLIDWORKS 2017 compatibility rules (ADR-0002)
- **The ProgID is not the problem.** On this machine `SldWorks.Application` and `SldWorks.Application.25` resolve to the same 2017 CLSID. Don't add registry hacks.
- **Every SW API member the code calls must appear in `tools/compat/sw2017_api_members.txt`** (`Interface.Member`).
  - SOLIDWORKS never changes a published signature; newer behavior ships as numbered variants (`SaveAs3`, `CreateMassProperty2`, …).
  - Confirmed **absent** in 2017: `IModelDocExtension.SaveAs2/SaveAs3`, `IModelDocExtension.CreateMassProperty2`.
- The typelib registry key reads `19.0`, but **that is hex**, so load it with `LoadRegTypeLib(guid, 0x19, 0)`.
- Late-binding pitfalls (pywin32 dynamic dispatch):
  - Route members that take arguments through `sw_core.flag_methods`.
  - Pass ByRef and typed values with `byref_long()`, `nothing()`, `double_array()`.
  - Never read a PROPGET-with-args member as a plain attribute.
- **Modal dialogs block COM forever.** Suppress them the way `dimension_dialog_suppressed` does.

## Live testing safety (ADR-0005)
- Attach only to a SOLIDWORKS that Zach launched. Never start or quit SW, and never call `ExitApp`.
- File writes go only under `sandbox/` (gitignored). Never open, save or overwrite Zach's real CAD files during tests.
- Before a live gate, ask Zach to save and close his own work.
- Verify by measurement (body count, volume, mass, feature tree, file exists and is non-empty), never by "no exception".

## Commands (PowerShell, repo root)
```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e .
.venv\Scripts\python.exe -m unittest discover -s tests -v      # offline unit tests (no SW needed)
.venv\Scripts\python.exe tools\compat\mcp_smoke_client.py      # MCP handshake + tools/list (no SW needed)
.venv\Scripts\python.exe tools\compat\dump_sw_tlb.py tools\compat\sw2017_api_members.txt  # regenerate 2017 API snapshot
.venv\Scripts\python.exe tests\live_p0_regression.py           # LIVE: SW 2017 must be running
```

## Modeling rules for the AI: "the brain" (ADR-0004, proposed)
- The rules the AI follows while modeling live in `rules/`.
- Whenever Zach states a modeling preference (e.g. "always top-down assemblies", "plan before building"), add it to `rules/candidates.md` with status `proposed` and confirm it at the next 🧑 gate.
- `docs/how-it-works.md` explains the client → MCP → COM → SOLIDWORKS stack. Keep it current; Zach is using it to learn.

## Repo conventions
- Our additions live in `docs/`, `rules/`, `tools/compat/`, `tests/test_sw2017_*.py` and `CLAUDE.md`. Keep diffs to upstream files minimal so `git merge upstream/main` stays easy.
- When modifying an upstream source file, add `# Modified for SOLIDWORKS 2017 support (fork).` under its Apache header (Apache-2.0 §4(b)), and log the change in `docs/FORK_CHANGES.md`.
- Match upstream style: type hints, and docstrings and comments that explain *why*.
- Git:
  - Work on `phase-N-<slug>` branches.
  - Commit and merge only with Zach's OK at a gate.
  - Never push tags; `.github/workflows/publish-mcp.yml` publishes upstream's package to PyPI and the MCP registry (ADR-0001).
