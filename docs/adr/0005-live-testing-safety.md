# ADR-0005: Live-testing safety on Zach's workstation

- **Status:** Accepted. Zach confirms the sandbox path and readiness at 🧑 G2.
- **Date:** 2026-10-08

## Context
The tests run against Zach's real SOLIDWORKS 2017 install, on the same machine that holds his real CAD data. Some tools can:
- write or overwrite files
- change user preferences (e.g. the dimension-input toggle)
- open modal dialogs that hang COM indefinitely

Upstream attaches only to a running session and never starts SW.

## Decision
- **Attach only.** Zach launches SOLIDWORKS 2017 and dismisses any startup dialogs. Tests never start SW, quit it, or call `ExitApp`.
- **Sandbox.** All test file I/O happens under `C:\_Projects\solidworks-mcp\sandbox\` (gitignored), in a per-run subfolder such as `sandbox\run-YYYYMMDD-HHMM\`. Tests never open, save or overwrite files elsewhere.
- **Before each live gate**, Zach saves and closes his own documents. Tests close only documents they created, without saving.
- **User preferences.** Any toggle a tool changes must be restored (upstream's `dimension_dialog_suppressed` pattern). The live suite records the preference values it touches before and after the run.
- **Hang handling.** Each live call runs under a watchdog timeout (default 60 s). On a timeout the run stops and asks Zach to look at the SOLIDWORKS window, usually to dismiss a dialog. No automatic retries.
- **Serial only** (ADR-0003). One live agent at a time.
- **Verification by measurement.** Each tool result is classified as PASS, FAIL (exception), SILENT-FAIL (no exception but wrong or missing geometry), HANG (timeout) or FENCED (disabled for 2017). Measurements include body count, volume, face count, feature names and types, mate count, view count, and output file existence and size.

## Consequences
- Live phases need Zach present, at least at the start, and have a fixed setup checklist (G2).
- Results are reproducible: each run has a sandbox folder plus `docs/reports/phase3-live-matrix.md`.
