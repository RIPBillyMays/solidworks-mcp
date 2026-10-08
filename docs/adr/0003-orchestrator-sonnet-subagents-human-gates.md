# ADR-0003: Orchestrator + Sonnet subagents, human gates, and context handoffs

- **Status:** Accepted (Zach's working-style request, 2026-10-08)
- **Date:** 2026-10-08

## Context
Zach wants:
1. the main Claude session to act as orchestrator, with Sonnet subagents doing implementation and testing
2. work to pause at human gates for his input
3. sessions to stay small, with a handoff written around 50% context so work continues in a fresh session

Live SOLIDWORKS is a single, stateful, single-threaded (COM STA) resource. A modal dialog blocks every caller.

## Decision
**Roles**
- **Orchestrator (main session).** Owns `docs/PLAN.md`, ADRs, task briefs, review, gates, handoffs and conversations with Zach.
- **Implementer subagents (`model: "sonnet"`).** Each gets one scoped task: allowed files, acceptance criteria, explicit don'ts. Reports are ≤150 words; long output goes to `docs/reports/`.
- **Verifier subagents (`model: "sonnet"`).** Independently re-run the tests and review the diff against the acceptance criteria. The implementer never self-certifies a 🧪 gate. The orchestrator spot-checks too, as it did for T1.

**Concurrency**
- Offline tasks (code, unit tests, docs, static analysis) may run in parallel when their file sets don't overlap.
- **Live SOLIDWORKS tasks run serially.** Only one agent touches SW at a time, and the orchestrator doesn't run offline jobs that also attach to SW at the same time.

**Gates** (defined in `docs/PLAN.md`)
- 🧪 test gates are automated and must pass.
- 🧑 human gates need Zach's decision. The orchestrator presents what was done, the evidence, and the decisions with a recommendation.
- 🔁 marks a handoff point.

**Context discipline**
- Write a handoff at about 50% context, at every 🧑 gate, and before each live phase. Use `docs/handoff/YYYY-MM-DD-NN-<slug>.md` from `TEMPLATE.md`. Upstream's `.gitignore` ignores files named `HANDOFF.md`, so we never use that name.
- The orchestrator never reads subagent transcripts. It reads reports and diffs.

## Consequences
- More, smaller sessions; every phase starts by reading the latest handoff plus PLAN status.
- The orchestrator can't measure context precisely. It estimates and errs early. Zach can also check `/context` in a terminal `claude` session and ask for a handoff at any time.
- Some overhead per task (brief plus verification), traded for reliability and a reviewable trail in `docs/reports/`.
