# Preservation contract

## Purpose

Treat preservation as an engine constraint, not a prompt preference. Color grading necessarily changes pixel values; strict preservation means retaining spatial structure, identity, objects, and the source texture field.

## Strict-mode whitelist

Allow only:

- ICC conversion and output profile assignment;
- exposure gain;
- global RGB white-balance gains;
- black and white point mapping;
- monotonic luminance curves and highlight roll-off;
- ASC-CDL-style slope, offset, power, and saturation;
- global saturation adjustment;
- low-strength split toning;
- smoothly feathered protection masks that only reduce a grade.

## Forbidden operations

Reject any recipe requesting:

- crop, resize, rotate, warp, perspective, or liquify;
- inpainting, outpainting, object replacement, or generative editing;
- face restoration, beauty filters, skin smoothing, or reshaping;
- blur, sharpen, denoise, clarity, texture, dehaze, or local-contrast enhancement;
- grain, dust, scratches, bloom, glow, or other texture synthesis;
- an unknown operation or arbitrary executable filter string.

Do not add a forbidden operation merely because a named style commonly includes it. A film look may reproduce its tone and color response without adding grain.

## Masks

Use masks only to reduce a color transform in protected regions. Never use a mask to synthesize, heal, sharpen, blur, or reshape content. Feather masks enough to avoid new visible boundaries. When mask confidence is low, disable or reduce the uncertain mask and review the global grade visually; do not automatically weaken the whole image.

The v0.1 skin mask is a feathered color heuristic, not face parsing. It can include wood, earth, or a globally warm scene. Treat coverage above 35% as uncertain, inspect the preview, and reduce or disable protection when it is overbroad. Preserve actual skin through globally safe color choices when the mask is unusable. Do not claim semantic face detection.

## Encoding

Decode the source once, process in floating point, and encode once. Prefer a lossless PNG master. A newly encoded JPEG cannot be pixel-identical to the source; label it as a lossy derivative and use high quality with minimal chroma subsampling.

## Honest limits

Do not describe tone compression as recovered detail. Fully clipped encoded pixels contain no recoverable scene information. RAW support may later expose sensor detail that is absent from an encoded JPEG, but v0.1 does not process RAW.
