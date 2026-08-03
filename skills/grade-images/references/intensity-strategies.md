# Intensity strategies

## Separate preservation from intensity

Keep `preservation.mode: strict` at every intensity. Conservative, standard, and bold describe how far tone and color may move, never whether geometry, identity, objects, facial features, or texture may change.

## Ask or infer

For a subjective `look` request with no clear intensity cue, ask the user to choose:

- **Conservative**: subtle cleanup; retain the source mood.
- **Standard**: clearly improved and visibly different without dominating the photograph.
- **Bold**: unmistakable creative treatment within clipping and gamut limits.

If the user does not answer and continuing is appropriate, use `standard` and say so. Do not ask again when the prompt already contains a clear cue.

Map language as follows:

- `保守`, `轻微`, `微调`, `克制`, `subtle`, `restrained` -> `conservative`
- no intensity cue -> ask; otherwise `standard`
- `放开调`, `强烈`, `大胆`, `浓郁`, `明显`, `极致`, `bold`, `dramatic` -> `bold`

Treat `自然`, `真实`, `电影感`, `胶片感`, and named moods as style cues, not intensity cues. In particular, `自然` never means `conservative` or `desaturated` by itself.

## Outcome targets

Use these as starting ranges, not rigid numeric goals. Scene analysis and clipping limits still govern the final values.

| Strategy | Visible outcome | Typical tone curve | Typical effective saturation | Typical split-tone strength |
| --- | --- | ---: | ---: | ---: |
| Conservative | Difference is visible side by side but does not announce itself | `0.04..0.16` | `0.97..1.06` | `0.00..0.05` |
| Standard | Difference is clear at fit-to-screen size | `0.16..0.36` | `0.95..1.12` | `0.04..0.12` |
| Bold | Treatment is unmistakable without clipping or fluorescent color | `0.30..0.58` | `0.92..1.22` | `0.09..0.18` |

Use only one saturation control away from `1.0`. The effective saturation is `look.cdl.saturation * look.saturation`; stacking two reductions caused the failed natural-beauty test.

## Interpret styles correctly

### Natural

Preserve believable relationships and signature colors. Correct casts using white balance and tonal shaping first. Do not reduce saturation merely because the source is colorful. Reduce chroma only where preview inspection shows clipping, hue breakage, or a fluorescent appearance. `极致自然美` maps to `natural + bold`: luminous, clean, and vivid while remaining plausible, with no split toning unless explicitly requested.

### Cinematic

Build the look through tonal density, controlled color separation, and subject emphasis. Cinematic does not automatically mean faded or desaturated. For standard and bold strategies, the before/after should be plainly distinguishable. Protect important colors such as skin, sky, foliage, product colors, or a red lighthouse instead of flattening the whole image.

### Reference

Expose strength explicitly. Treat `0.35`, `0.65`, and `0.90` as conservative, standard, and bold starting points. Report when source/reference differences prevent a strong safe match.

## Preview decision

Label every preview with style and intensity. For `standard` or `bold`, treat a low-difference warning from `compare.py` as a reason to revise the recipe, not as a successful result, unless clipping/gamut limits are documented. When uncertain between two interpretations, offer two previews rather than silently choosing the weaker one.
