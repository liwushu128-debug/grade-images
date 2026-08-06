# Texture refinement boundary

## Default

Keep texture unchanged. Omit the `texture` object and require `allow_texture_changes: false` for correction, matching, film color, documentary color, and ordinary creative grading. A style word never grants texture permission.

Use v0.3.4 texture refinement only when the user explicitly requests sharpening or output sharpening and the source is already correctly focused. State that the operation cannot recover detail, repair blur, or create information.

## Allowed refine operation

Allow only bounded, source-derived luminance output sharpening:

- apply after color and tone at the actual output resolution;
- derive the detail signal only from the rendered source pixels;
- keep `amount` in `0..0.35`, `radius_pixels` in `0.5..1.5`, and `threshold` in `0.005..0.04`;
- cap per-pixel luminance change at `0.035`;
- protect likely skin and dark/noisy regions by default;
- preserve dimensions, alpha, RGB chroma differences, objects, text, and geometry.

Do not add denoise, deblur, super-resolution, face restoration, defect repair, grain, dust, scratches, blur, clarity, dehaze, local contrast, skin smoothing, or arbitrary kernels. These operations have no recipe representation and must fail closed.

## Evidence learned from the documentary examples

Eight private Before/After composites were measured after robust luminance normalization. Do not bundle the source images.

- Pairs 1–4: mean edge-energy ratios were approximately `1.24`, `1.01`, `1.32`, and `1.34`; P90 edge ratios were `1.21`, `1.08`, `1.40`, and `1.33`. This supports an optional crisp documentary output, but the strongest examples exceed the safe automatic range.
- Pairs 5–8: mean edge-energy ratios were approximately `0.84`, `0.95`, `0.76`, and `0.74`; high-pass variation fell by roughly `6%..39%`. Those examples also contain softness, grain, dust, or aged-surface character. Do not reproduce those texture traits because they require blur, smoothing, or synthetic texture.

Use `documentary-vivid-refine.json` only after an explicit sharpening request. Keep `documentary-vivid-standard.json`, `documentary-archive-standard.json`, and `documentary-earth-standard.json` color-only by default.

## Quality gates

Inspect the preview at 100%. Warn when sharpening raises mean edge energy by more than `22%`, P90 edge energy by more than `25%`, or high-frequency variation by more than `25%`. Also retain the existing orientation and new-edge gates. Reduce only sharpening amount when a texture warning occurs; do not compensate with exposure, contrast, or color.

Reject the result when halos, doubled contours, amplified JPEG blocks, roughened skin, fluorescent foliage edges, or newly visible false detail appear even if numeric gates pass.
