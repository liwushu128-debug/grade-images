# Quality gates

## Hard failures

Fail the result when:

- the input path and output path resolve to the same file;
- image width, height, channel count, or alpha structure changes;
- the source file hash changes;
- recipe validation fails;
- an unknown or forbidden operation is requested;
- the output cannot be decoded or its format disagrees with the recipe;
- rendering produces non-finite pixel values.
- an enabled effect lacks explicit consent or requests anything other than source-derived glow;
- an effect creates a detached synthetic light shape or visible light with no supporting source highlight.

## Warnings

Warn when:

- output clipping increases materially;
- more than a small fraction of pixels reaches extreme saturation;
- skin protection is enabled but no reliable skin region is detected;
- a heuristic skin mask covers more than 35% of the image and may include non-skin colors;
- the grade creates strong differences at a protection-mask boundary;
- JPEG output is requested;
- metadata or ICC data cannot be preserved in the chosen format.
- a `standard` or `bold` strategy produces too little visual difference for the selected intensity;
- a `conservative` strategy produces an unexpectedly large difference.
- a reference-guided output misses the intensity-specific distribution-improvement target;
- source glow excessively obscures important high-frequency detail or creates a new strong edge.

Treat low-difference warnings as intent failures, not preservation successes. A structurally safe result can still fail the user's aesthetic request.

## Structural checks

Raw SSIM is not a preservation proof because legitimate exposure and tone changes alter it. Compare structure using:

- dimensions and channel topology;
- edge-location agreement after rank-normalizing luminance;
- gradient-orientation agreement at strong source edges;
- newly introduced strong edges in formerly smooth regions;
- deterministic output hashes for repeated identical runs.

Use these metrics as alarms. The primary guarantee remains the strict operation whitelist and an engine that lacks geometry, synthesis, and texture operators.

Source glow is a bounded exception that operates only on an extracted low-frequency light layer. Inspect the unblurred base and the final output at 100%; its presence does not relax geometry, identity, object, text, or content preservation.

## Aesthetic difference checks

Record mean absolute RGB difference, P95 per-pixel RGB difference, mean absolute luminance difference, and the fraction of pixels changing by at least `2/255`. These are not beauty scores. Use them only to catch a mismatch between the selected intensity and a nearly unchanged output.

## Reference-aware checks

When a reference is supplied, record source-to-reference and output-to-reference distribution distances using luminance percentiles, saturation statistics, and channel means. Require at least 20%, 40%, or 60% improvement for conservative, standard, or bold matching. Keep preservation status separate from target-match status.

Use the larger of source and reference clipping, near-black, and extreme-saturation fractions as the baseline before warning. Do not force a deliberately strong reference back toward neutral merely because its target distribution contains deep blacks or saturated colors.
