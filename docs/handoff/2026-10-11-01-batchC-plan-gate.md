# Handoff: 2026-10-11-01 Batch C plan at gate G-C0; Desktop config fixed (pending Zach's run)

## Resume prompt
`Read CLAUDE.md, then docs/handoff/2026-10-11-01-batchC-plan-gate.md, then continue from "Next steps".`

## Where we are
- **Branch:** `phase-5-clients-guided`. Uncommitted:
  - `docs/plans/phase5-batchC-plan.md`
  - `docs/adr/0007-…` (Proposed)
  - `docs/reports/phase5-batchC-inputs.md`
  - `tools/compat/register_claude_desktop.ps1`
  - the `docs/clients.md` Desktop section
- **Live check 2026-10-11:** `solidworks_status` connected (25.5.0), `output_root=…\sandbox`, 0 docs open. Smoke client lists 146 tools.

## Done
- **Desktop root cause:** the app rewrites `%APPDATA%\Claude\claude_desktop_config.json` from memory on every session/connector event. Evidence: `Config file written` in `%LOCALAPPDATA%\Claude\Logs\main.log`. So edits made while Desktop runs are lost.
  - Not an MSIX redirect, not a policy.
  - Fix: `register_claude_desktop.ps1`, run while Desktop is fully quit. It refuses to run if Desktop is up.
- Batch C plan and ADR-0007 drafted.

## Next steps
1. Zach: run the Desktop registration and the T5 Desktop test (steps in the session reply and `docs/clients.md`). Record the result in `docs/reports/phase5-t5-desktop.md`.
2. Zach decides D1–D6 at G-C0 (in the plan).
3. On approval: C0 (Sonnet: typelib probe, module stubs, flag hook), then C1/C2/C3 offline in parallel, then live C2 → C3 → C1, serial, with a handoff before each.
