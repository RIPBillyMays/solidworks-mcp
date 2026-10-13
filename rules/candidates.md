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

### R-010: Check `output_root` before building
- **Enforcement:** soft
- **Applies to:** all
- **Rule:** Call `solidworks_status` first and confirm `output_root` is the approved sandbox before building anything that will be saved. If it is not, stop and tell Zach rather than saving elsewhere.
- **Why:** Phase 5 T5: the Claude Code registration had no `SW_MCP_OUTPUT_ROOT`, so the finished part could not be saved. It was found only at the end. *(proposed, 2026-10-10)*

### R-011: Re-list faces before every selection
- **Enforcement:** soft
- **Applies to:** part
- **Rule:** Face indices and body names change after each feature. Re-run `list_faces` with a filter (normal, area, point) immediately before every face selection. Never reuse an index from an earlier listing.
- **Why:** Phase 5 T5: indices moved after the cut, and the body was renamed "CenterHole". *(proposed, 2026-10-10)*

## Field-use candidates (2026-10-12)
Source: a multi-part build driven from another project (`docs/handoff/2026-10-12-01-mcp-field-findings.md`). All seven were **confirmed** by Zach at 🧑 G5 (2026-10-13) as soft rules; like R-009 they become active when the Phase 6 rulebook ships. R-013 remains a hard-gate candidate.

### R-012: Shared frame for multi-part products
- **Enforcement:** soft
- **Applies to:** assembly
- **Rule:**
  - Model every part in place, in one shared product frame.
  - Insert every component at the assembly origin.
  - Get mirrored or turned copies with `rotate_component`, not by re-modeling the part.
- **Why:** In the field build, origin-located inserts landed exactly. That made placement free, and `interference_detection` meaningful.

### R-013: Verify every feature by measurement
- **Enforcement:** soft (hard candidate)
- **Applies to:** part
- **Rule:**
  - After each feature, compare the volume change (`get_mass_properties`) against a hand calculation.
  - Check `check_errors`.
  - Check specific vertices or the bounding box where it matters.
  - A tool returning ok, or raising no exception, is not proof.
- **Why:** In the field, volume deltas matched hand calculations on every cut and were the most reliable signal. Silent wrong geometry cost hundreds of calls.

### R-014: Sketch with exact-geometry tools and check the read-back
- **Enforcement:** soft
- **Applies to:** part
- **Rule:**
  - Prefer `draw_polyline`, `draw_rectangle` and `draw_polygon` over chains of `draw_line`.
  - Treat `ok:false` with `requested`/`actual` as a hard stop. Don't work around it.
  - Use `list_sketch_segments` to confirm intent before extruding.
- **Why:** Sketch snapping in crowded sketches produced wrong profiles that the tools reported as ok. This was fixed 2026-10-12 (field finding #1), but the read-back stays the safety net.

### R-015: Geometry calls are serial; know which document is active
- **Enforcement:** soft
- **Applies to:** all
- **Rule:**
  - Issue one modeling call at a time.
  - Read `active_document` in each result. Switch documents with `activate_document`, never by assumption.
  - Make sure no other client drives SOLIDWORKS at the same time.
- **Why:** Field reports of the document flipping mid-sequence. The probe found a second client/session active alongside it (2026-10-12).

### R-016: Assembly acceptance needs zero interferences
- **Enforcement:** soft
- **Applies to:** assembly
- **Rule:** An assembly isn't done until `interference_detection` reports 0, or Zach accepts each listed interference.
- **Why:** In the field it found a real 1 mm sketch error that bounding-box checks missed.

### R-017: Fall back after two failures of an advanced feature
- **Enforcement:** soft
- **Applies to:** part
- **Rule:**
  - If a loft, variable fillet or other advanced feature fails twice, fall back to a simpler equivalent: extrude + cut, or a uniform fillet.
  - Record the deviation in the build report for Zach.
- **Why:** In the field, loft and variable-fillet failures with no detail burned many calls (findings #16, #17).

### R-018: Brief subagents with a resolved numeric spec and the quirks list
- **Enforcement:** soft
- **Applies to:** all (orchestrated builds)
- **Rule:** A modeling subagent's brief contains:
  - every coordinate and dimension, fully resolved
  - which sketch axes map to which model axes for the chosen plane (returned by `create_sketch` once #15 lands)
  - the current known-quirks list
- **Why:** In the field, adding the quirks list cut a comparable part from about 300 to about 110 calls.
