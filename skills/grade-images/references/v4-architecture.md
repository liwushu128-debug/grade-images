# v0.4.0 graph architecture

Use v0.4.0 when a request benefits from auditable separation between language interpretation, scene evidence, recipe compilation, execution, and bounded correction.

The pipeline writes three versioned records:

- `intent-ir.json` records prompt-derived intent, source facts, strict preservation constraints, effect and texture permissions, routing, and provenance.
- `evidence-graph.json` records measured and visually supplied evidence plus the exact decisions it supports. Its canonical hash must be deterministic.
- `render-graph.json` records the ordered executable nodes, compiled recipe, backend, compatibility contract, and canonical hash.

The fixed node order is decode, color management, correction, look, protection, effects, texture, gamut handling, then encode. Effects and texture nodes remain inactive unless their independently recorded permissions and recipe blocks enable them.

The `legacy-fused-v1` backend is the v0.4.0 compatibility backend. For the same compiled recipe it must produce exactly the same floating-point pixels as the pre-v0.4 renderer. Routing may explicitly disable an uncertain protection mask before compilation; that decision must remain visible in the intent IR and compiled recipe.

The closed-loop controller retains a two-round limit. On low-key sources it may soften the tone curve while scaling existing color-separation parameters and independently restraining global saturation. It may not add a new aesthetic axis, change exposure merely to satisfy a difference floor, grant effects or texture permission, or accept an output with unresolved warnings.

Keep all graph records, the selected recipe, quality report, controller manifest, final image, and comparison sheet together. A graph hash proves deterministic compilation of recorded inputs, not visual quality; the quality gates and visual inspection remain mandatory.
