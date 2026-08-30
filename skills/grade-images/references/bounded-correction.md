# Bounded correction

Use bounded correction only after a preview report contains mapped quality or
intent warnings. It is a deterministic two-round budget, not an open-ended
optimizer.

Run:

```text
python scripts/correct.py INPUT --recipe RECIPE.json \
  --route ROUTE.json --output-dir correction --max-size 1200
```

Supply the route record whenever scene routing affected skin protection. The
input hash in the route must match. A `review` skin decision stops correction
until the visual ambiguity is resolved.

The controller maps warnings to causes and changes only allowed axes:

- shadow crush: reset an added black point and search a bounded lower S-curve;
- underpowered intent: scale the existing creative color-separation axis within recipe limits;
- chroma clipping: reject stronger candidates through the existing quality gate;
- structure change, highlight clipping, or an unknown warning: stop for review.

The first round records the original result. The second round evaluates a fixed
candidate bracket and selects the lowest-cost candidate that clears safety and
intent warnings. If none passes, stop with `needs-review`; never run a third
round, change exposure merely to raise a difference score, or cross the selected
intensity boundary.

Keep the manifest, selected recipe, quality report, corrected image, and labeled
comparison sheet together. Treat a `needs-review` result as a failed automatic
correction, not as a deliverable pass.
