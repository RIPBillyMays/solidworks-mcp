# ADR-0001: Fork Slacker-LLC/solidworks-mcp as the base server

- **Status:** Accepted (Zach approved "fork it and install", 2026-10-08)
- **Date:** 2026-10-08

## Context
We want Claude and other AI clients to drive the local SOLIDWORKS 2017 SP05. We considered building from scratch versus forking an existing Python COM MCP server. On 2026-10-08 we statically checked 8 candidates against the installed 2017 type library (`tools/compat/sw2017_api_members.txt`):

| Candidate | License | 2017-missing calls | Verdict |
|---|---|---|---|
| yimu0824/solidworks-mcp | MIT | n/a | Rejected: 2 files, read-only tools, `Extension.SaveAs` called with 7 args (it takes 6), unregistered ProgID `SldWorks.StlExportOptions` |
| **Slacker-LLC/solidworks-mcp** (formerly limuzi013) | Apache-2.0 | none (one unused flag name, `SaveAs3`) | **Chosen** |
| alisamsam/Solidworks-MCP | MIT | `Extension.SaveAs2` ×3 | Fallback #1 |
| HarrierPigeon/Solidworks-MCP-Server | MIT | none found | Fallback #2 (smaller tool set, depends on FeatureWorks) |
| andrewbartels1/SolidworksMCP-python | MIT | `SaveAs2`, others | Too large (~115k lines) to own |
| vespo92/SolidworksMCP-TS | MIT | `CreateMassProperty2`, `RunCheck3`, … | TypeScript, many post-2017 calls |
| eyfel/mcp-server-solidworks | AGPL-3.0 | n/a | C# built against 2026 interop; copyleft |

Why Slacker-LLC: 92 tools (sketch, features, reference geometry, assemblies, drawings, screenshots), about 6.6k lines, and it attaches to a running session via the version-independent ProgID. It also already handles the main pywin32 late-binding hazards (`flag_methods`, typed VARIANT helpers, dimension-dialog suppression), ships a type-library probe and 24 offline unit tests, and runs stdio-only (no network surface).

## Decision
- Fork `Slacker-LLC/solidworks-mcp` to `RIPBillyMays/solidworks-mcp` (`origin`) and keep `upstream` as a remote.
- **Minimal-diff policy:** our work lives in new files (`docs/`, `rules/`, `tools/compat/`, `tests/test_sw2017_*.py`). Edits to upstream files stay small and are logged in `docs/FORK_CHANGES.md`.
- **Apache-2.0 compliance:** keep `LICENSE` and `NOTICE`. Each modified upstream file gets `# Modified for SOLIDWORKS 2017 support (fork).` under its header (§4(b)).
- **Disable publishing:** `.github/workflows/publish-mcp.yml` pushes upstream's package to PyPI and the MCP registry on `v*` tags. We never push tags, and in Phase 7 we delete or disable that workflow in the fork (forks don't hold the secrets, but a failed publish run is noise and a latent risk).
- Python 3.12 venv via `uv` (upstream CI covers 3.10–3.13; 3.14 is untested by upstream).

## Consequences
- We inherit upstream's architecture: low-level `mcp.server.Server` (not FastMCP) and `mcp>=1.29,<2`. MCP SDK 2.0 is a separate port.
- Upstream was exercised on SOLIDWORKS 2026 SP3.2. 2017 runtime behavior is unknown until Phase 3. The static check proves names exist, not that behavior matches.
- Syncing upstream means `git fetch upstream && git merge upstream/main`, followed by the T2 compat gate (see PLAN).
- If Phase 3 fails the core part workflow badly, revisit this ADR and evaluate Fallback #1 or #2 on the same live matrix.
