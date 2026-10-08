# Architecture Decision Records

Format: Context → Decision → Consequences (→ Alternatives). A decided ADR is never edited to change its outcome. To change a decision, write a new ADR that supersedes it.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-fork-slacker-llc-solidworks-mcp.md) | Fork Slacker-LLC/solidworks-mcp as the base server | Accepted |
| [0002](0002-sw2017-compat-is-api-availability.md) | SW 2017 compatibility is API availability, not ProgID/registry | Accepted |
| [0003](0003-orchestrator-sonnet-subagents-human-gates.md) | Orchestrator + Sonnet subagents, human gates, context handoffs | Accepted |
| [0004](0004-modeling-rules-delivered-by-server.md) | Modeling rules are a server-delivered rulebook with selective hard gates | **Proposed** (G1/G6) |
| [0005](0005-live-testing-safety.md) | Live-testing safety on Zach's workstation | Accepted |

Expected next: ADR-0006, the version-fencing mechanism for tools that can't work on 2017 (Phase 4, if needed).
