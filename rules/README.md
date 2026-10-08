# Modeling rulebook ("the brain")

These are the rules an AI follows when it drives SOLIDWORKS through this server. See ADR-0004 for how they reach any MCP client (server instructions, resources, prompts and selective hard gates). Until Phase 6 ships, the rules are documentation only.

## Lifecycle
`proposed` → (Zach approves at a 🧑 gate) → `active` → (stops earning its keep) → `retired`

Every change is logged in `CHANGELOG.md`.

## Rule format
Each active rule will live in a topic file (`planning.md`, `assembly.md`, `sketching.md`, `features.md`, `verification.md`, `files.md`) as:

```markdown
### R-NNN: <imperative title>
- **Status:** proposed | active | retired
- **Enforcement:** soft (instructions/prompt) | hard (tool refuses) | soft→hard candidate
- **Applies to:** part | assembly | drawing | all
- **Rule:** <one or two sentences the model can follow without interpretation>
- **Why:** <design-intent / failure it prevents>
- **Do:** <short example>
- **Don't:** <short example, ideally a real mistake from a retro>
```

## Writing good rules
- **Be specific.** "Fully define every sketch before creating a feature from it" beats "make good sketches".
- **Explain why.** Models generalize from the reason, not only the wording.
- **Tie rules to real mistakes.** Each `Don't` should ideally be a real mistake from a retro.
- **Make rules checkable where you can.** A rule you can check is a candidate for a hard gate.
- **Keep the core summary short.** The server's `instructions` should stay ≤ ~40 lines; detail lives in resources.
