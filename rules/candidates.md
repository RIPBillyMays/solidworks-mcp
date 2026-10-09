# Rule candidates (all `proposed`; Zach approves at a 🧑 gate)

Seeded 2026-10-08 from Zach's stated goals and common SOLIDWORKS design-intent practice. None of these are active yet.

### R-001: Plan the build before touching SOLIDWORKS
- **Enforcement:** hard candidate (`record_build_plan` gate, ADR-0004)
- **Applies to:** all
- **Rule:** Before any modeling tool call, write a build plan and get Zach's OK. The plan covers:
  - design intent (what must stay true when dimensions change)
  - units
  - origin and datum strategy
  - ordered feature list (sketch plane → sketch → feature)
  - assembly strategy, if any
  - how each step will be verified
- **Why:** The AI can't see the screen continuously, so re-ordering features after the fact is expensive. A plan also lets Zach catch design-intent mistakes for the cost of reading a list.
- *Source: Zach, 2026-10-08 ("plan out how we are going to build it in solidworks before we dive in").*

### R-002: Propose the assembly strategy per project; Zach approves
- **Enforcement:** soft (carried by the `plan_assembly` prompt and approval of the plan)
- **Applies to:** assembly
- **Rule:** Every assembly build plan **proposes** top-down or bottom-up, with the reason, and waits for Zach's approval before any assembly is created.
  - **Top-down:** a layout or skeleton sketch drives in-context parts; mate to the skeleton.
  - **Bottom-up:** independent parts, then mates referencing part planes, axes and origins.
  - There is no fixed default. The choice is per project. *(Decided by Zach at G1, 2026-10-08.)*
- **Why:** Mixing strategies by accident creates fragile external references and circular dependencies.
- *Source: Zach, 2026-10-08 ("always do top down vs bottom up assemblies").*

### R-003: Anchor geometry to the origin and base planes
- **Enforcement:** soft
- **Applies to:** part
- **Rule:** The first sketch sits on a base plane (Front, Top or Right) and references the origin. Symmetric parts are centered on the origin.
- **Why:** Stable references make mates, patterns, mirror features and later edits predictable.

### R-004: Fully define sketches before creating features
- **Enforcement:** soft→hard candidate (sketch status is queryable)
- **Applies to:** part
- **Rule:** Every sketch is fully defined, using dimensions and relations rather than fixed geometry, before any feature consumes it.
- **Why:** Under-defined sketches change shape unpredictably when the model is edited.

### R-005: Verify after every feature
- **Enforcement:** soft
- **Applies to:** all
- **Rule:** After each feature, confirm the result by measurement: body count, volume or mass change, and any rebuild errors. Take a screenshot at milestones. If a result is unexpected, stop and report it rather than piling on more features.
- **Why:** A wrong feature found late cascades into everything built on it.

### R-006: Name what matters
- **Enforcement:** soft
- **Applies to:** all
- **Rule:** Rename key sketches, features and planes to their intent, e.g. `SK_BaseProfile` or `Boss_Base`. Leave generic names only on trivial features.
- **Why:** A readable feature tree helps both Zach and later AI sessions.

### R-007: Sandbox-only file writes until allowed otherwise
- **Enforcement:** hard candidate
- **Applies to:** all
- **Rule:** Only save or export under the approved sandbox folder, unless Zach explicitly names another path in the current request.
- **Why:** Protects real CAD data (ADR-0005).

### R-008: Work in millimetres unless told otherwise
- **Enforcement:** soft
- **Applies to:** all
- **Rule:** Every dimension in plans, tool arguments and reports is in **mm** (angles in degrees) unless Zach specifies other units for the request. State the units in the build plan.
- **Why:** This is Zach's default unit system *(G1, 2026-10-08)*. The server converts to SOLIDWORKS's internal metres at the boundary.

### R-009: Edge breaks are fillet/chamfer features, not sketch geometry
- **Enforcement:** soft (status **confirmed** by Zach at 🧑 G4, 2026-10-09; becomes active with the Phase 6 rulebook)
- **Applies to:** part
- **Rule:** Round or bevel model edges with the `fillet` and `chamfer` **features**, applied to body edges after the base shape exists. Do not bake rounds or bevels into sketch profiles with `sketch_fillet` or `sketch_chamfer`. Sketch fillets and chamfers are reserved for shapes that really are profile geometry, such as a slot end or a cam profile, and the build plan says why.
- **Why:** Edge-break features are separate, suppressible and editable in the feature tree. Keeping them out of the sketch keeps the sketch simple and fully defined, and lets Zach change or remove a break without reworking the profile. This is common SOLIDWORKS practice (cosmetic features last).
- *Source: Zach, 2026-10-09 (G4: "are you using the chamfer feature … and the fillet features on the edges and not making the changes in the sketch profiles?").*
