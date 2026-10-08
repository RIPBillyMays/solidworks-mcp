# ADR-0004: Modeling rules ("the brain") are a server-delivered rulebook with selective hard gates

- **Status:** Proposed. Decide the direction at 🧑 G1 and approve the rule set v0 at 🧑 G6.
- **Date:** 2026-10-08

## Context
Zach wants the AI to follow learned modeling discipline. Examples:
- always plan the build before touching SOLIDWORKS
- prefer top-down (or bottom-up) assemblies

The rules must apply in **any** MCP client (Claude Desktop, Claude Code, Cursor, Codex, Gemini CLI), not only in this repo's Claude Code sessions. Today the server sends **no `instructions`** at initialize (verified in the Phase 1 smoke test). The only guidance an AI receives is the 92 tool descriptions.

There are several levers for steering an AI, from weakest to strongest:
1. Zach's prompt in the chat.
2. Client-side files (`CLAUDE.md`, Claude skills). These only work in one client.
3. **MCP server `instructions`.** Sent at the handshake; most clients add them to the model's system prompt.
4. **Tool descriptions.** Read every time the model considers a tool, and highly influential.
5. **MCP prompts.** Named workflows the user can invoke, e.g. `plan_part` or `plan_assembly`.
6. **MCP resources.** Documents the model can read on demand, e.g. the full rulebook.
7. **Hard gates in tool code.** A tool refuses to act until a precondition holds, e.g. "no modeling until a build plan is recorded".

## Decision (proposed)
**Single source of truth**
- Rules live in `rules/` as markdown. Each rule carries an id, a status (`proposed` / `active` / `retired`), an enforcement level (`soft` / `hard`), a rationale and examples.

**Delivered by the server**, so every client gets them:
- `instructions`: a short core summary, ≤ ~40 lines and auto-generated from active rules. It tells the model to read the rulebook resource before modeling.
- Resources: `rules://index` plus one resource per rule file.
- Prompts: `plan_part`, `plan_assembly`, `review_model`. These walk the model through a plan template (design intent, datum strategy, feature order, assembly strategy, verification checks) and ask Zach to approve it.

**Hard gates only where a rule is mechanically checkable.** The first candidate is plan-before-build:
- A `record_build_plan` tool stores the approved plan in session state.
- While `SW_MCP_REQUIRE_PLAN=1`, modeling tools return a clear refusal until a plan exists. Read-only and inspection tools are never gated.

**Learning loop**
- After each real modeling session there's a short retro. Mistakes become `proposed` rules, Zach approves them at the next gate, and every change is logged in `rules/CHANGELOG.md`.

## Consequences
- The server gains prompts, resources and instructions. These are additive changes in a new module, with the upstream diff limited to registration in `server.py`.
- Soft rules can still be ignored by a model. Only hard gates guarantee behavior, so we promote a rule to hard when the retros show soft enforcement failing.
- Strategy-level rules (top-down vs bottom-up) stay soft, because judging them needs design understanding, not a mechanical check. They're carried by the plan template plus Zach's approval of the plan.

## Alternatives considered
- **Client-only (CLAUDE.md or a Claude skill).** Fast, but doesn't reach other clients. We may still mirror the rules into a Claude skill for convenience.
- **Hard-gate everything.** Brittle, and blocks legitimate exploration.
- **Rules only in tool descriptions.** Strong signal, but it bloats all 92 descriptions and causes churn against upstream.
