---
name: grade-images
description: Analyze, correct, match, and batch color-grade JPEG and PNG photographs with a deterministic, non-generative pipeline. Use whenever the user asks to color grade, color correct, fix exposure or white balance, match a reference image's color treatment, make a photo set visually cohesive, create a cinematic or film-like look, or apply a reproducible grade without changing geometry, identity, facial features, objects, or texture.
---

# Grade Images

Create reproducible photo color grades while preserving spatial structure, identity, and texture. Let visual reasoning choose intent and parameters; let the bundled deterministic renderer change pixels.

## Non-negotiable defaults

- Never overwrite an input image.
- Default to `preservation.mode: strict`.
- Keep preservation strict at every aesthetic intensity. Do not confuse structural safety with a weak color grade.
- Never use a generative image editor for a color-only request.
- Never claim to recover detail that is clipped in an encoded JPEG or PNG.
- Render a low-resolution preview before a full batch when the requested look is subjective.
- Save the exact recipe beside every final result.
- Fail closed when a recipe contains an unknown or texture-changing operation.

Read [preservation.md](references/preservation.md) before rendering. Read [recipe-schema.md](references/recipe-schema.md) before authoring or modifying a recipe. Read [intensity-strategies.md](references/intensity-strategies.md) before interpreting a subjective look or strength request. Read [quality-gates.md](references/quality-gates.md) before accepting final outputs. For color decisions and parameter interpretation, read [color-science.md](references/color-science.md).

## Choose a mode

- `audit`: inspect files and report technical characteristics without changing them.
- `correct`: correct exposure, white balance, clipping risk, and tonal balance without adding an aesthetic look.
- `look`: apply a described creative color treatment after technical correction.
- `match`: derive a safe color treatment from a reference image without neural style transfer.
- `batch`: normalize each source independently, then apply one shared creative look.

Do not treat identical parameters as perceptual consistency. For a batch, keep per-image correction separate from the shared look.

## Preflight

1. Locate the skill directory and use its bundled scripts by absolute path.
2. Require Python 3.10+, Pillow, and NumPy. If unavailable, stop and report the missing dependency; do not silently switch to a generative editor.
3. Accept single-frame, 8-bit JPEG and PNG in v0.1. Reject animation and higher-bit-depth inputs instead of silently losing frames or precision. Preserve dimensions and alpha structure. Convert a valid embedded ICC profile to the sRGB working/output space; preserve supported EXIF data when requested. Record a warning when an embedded profile is invalid or an untagged CMYK JPEG requires an uncertain default conversion.
4. Determine whether the user supplied a reference image, a named look, or only a correction request. Separately determine aesthetic intensity: `conservative`, `standard`, or `bold`.
5. For a subjective look with no clear intensity cue, ask the user to choose conservative, standard, or bold. If no answer is available and continuing is appropriate, use standard and state that choice. Never silently default a subjective look to conservative.

## Interpret intent

- Treat preservation and aesthetic intensity as independent controls. Keep geometry, identity, facial features, objects, and texture protected even for a bold grade.
- Treat `natural` as a style, not a synonym for low saturation or low intensity. Preserve vivid signature colors unless the preview shows clipping, hue breakage, or fluorescence.
- Treat `cinematic` as tonal density and controlled color separation, not automatic fading or desaturation.
- Map explicit phrases such as `保守`, `轻微`, or `克制` to conservative; map `放开调`, `强烈`, `浓郁`, `明显`, `大胆`, or `极致` to bold.
- When the user changes direction, rebuild the creative look from the new intent. Do not retain incompatible assumptions from the previous recipe.

## Workflow

### 1. Analyze

Run:

```text
python scripts/analyze.py INPUT [INPUT ...] --output analysis.json
```

Use the measurements as evidence, not as an automatic aesthetic verdict. Inspect the images visually as well. Identify the subject, important skin tones, lighting conditions, likely neutral areas, and requested mood.

### 2. Author a recipe

Start from `assets/recipes/neutral-correction.json`, `natural-standard.json`, `muted-cinematic.json`, `bold-cinematic.json`, or the shadow-safe `low-light-cinematic.json`. Keep technical correction and creative look in separate sections. Record the chosen style, intensity, and selection method under `strategy`, and explain subjective decisions under `intent`.

Use only one saturation control away from `1.0`. The renderer multiplies `look.cdl.saturation` and `look.saturation`; adjusting both caused unintended desaturation in testing and now fails validation.

Validate before rendering:

```text
python scripts/grade.py validate RECIPE.json
```

Unknown fields and forbidden operations must fail validation.

For a reference image, derive a recipe at the selected strength:

```text
python scripts/match.py SOURCE REFERENCE --template assets/recipes/neutral-correction.json --strength 0.65 --output match.json [--disable-skin-protection]
```

Use approximately `0.35`, `0.65`, or `0.90` for conservative, standard, or bold. Inspect the generated diagnostics and preview the recipe. A derived match is a starting point, not an aesthetic ground truth.

### 3. Render a preview

```text
python scripts/grade.py render INPUT --recipe RECIPE.json --output PREVIEW.png --max-size 1600
```

Label the preview with the selected style and intensity, then show it beside the original. For subjective or batch work, obtain confirmation before full-resolution rendering. A standard preview should be clearly different at fit-to-screen size; a bold preview should be unmistakably different. If it is not, strengthen the recipe or explain the clipping/gamut limit. Adjust one conceptual dimension at a time, such as warmth, contrast, saturation, or shadow color.

### 4. Render final images

```text
python scripts/grade.py render INPUT --recipe RECIPE.json --output OUTPUT.png
```

Prefer PNG for a lossless graded master. When the user needs JPEG, encode once from the original decode at quality 95 or higher. Never chain intermediate JPEG files.

For a batch, create one recipe per image containing its correction section and the same shared `look` section. Keep the recipe files with the outputs.

Generate those per-image recipes with:

```text
python scripts/batch.py INPUT [INPUT ...] --look LOOK.json --strength 0.8 --output-dir recipes [--disable-skin-protection]
```

Review `batch-manifest.json` for correction outliers before rendering. Render each image from its original file with its corresponding recipe.

Disable skin protection after visual inspection when the scene contains no people or the heuristic mask is overbroad. Keep it enabled only when the preview confirms useful coverage.

### 5. Verify

Run:

```text
python scripts/compare.py INPUT OUTPUT --recipe RECIPE.json --output report.json
```

Treat a failed hard gate as a failed deliverable. Report warnings about new clipping, JPEG loss, aggressive skin shifts, or uncertain masks. Do not describe a warning as a pass.

Review the `difference` section. For standard or bold strategies, do not accept a low-visual-delta warning merely because structural gates passed. Revise the aesthetic recipe unless a documented technical limit prevents the requested strength.

## Match a reference safely

Analyze source and reference separately. Match these components independently:

1. luminance distribution and contrast;
2. overall white-balance direction;
3. chroma intensity;
4. shadow, midtone, and highlight color tendencies;
5. protected skin response.

Convert the comparison into an ordinary recipe and render it through the same strict engine. Do not copy pixels, synthesize content, or use neural style transfer. Expose the same conservative, standard, or bold strength choice used for other subjective looks.

## Output contract

For each completed task, provide:

- graded image files;
- the exact versioned JSON recipe;
- a machine-readable quality report;
- a concise human summary of corrections, creative choices, and warnings.

Keep the original files untouched. State clearly when an output is a lossy JPEG derivative rather than the lossless master.
