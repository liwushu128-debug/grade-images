# Classic documentary color routing

## Scope

Interpret classic-documentary language as a tone-and-color family under strict preservation. Run:

```text
python scripts/route_documentary.py "PROMPT" [--output route.json]
```

The router does not inspect pixels or render. Analyze the source normally, keep technical correction separate, and treat its selected recipe as a creative baseline.

## Sample-informed evidence

Eight user-supplied local Before/After composites showed two repeatable clusters. The private images are not bundled with the skill.

- Pairs 1-4: median linear-luminance changes at P05/P50/P95 were approximately `-0.022/-0.076/-0.020`; median saturation changes at P50/P95 were `+0.245/+0.359`. This supports dense mids, anchored shadows, warm/cool separation, and strong muted-color expansion.
- Pairs 5-8: median linear-luminance changes at P05/P50/P95 were approximately `-0.002/-0.037/-0.044`; median saturation changes at P50/P95 were `+0.058/-0.013`. This supports softened archival tone, warm cream highlights, olive-cyan shadows, and restrained peak chroma. Pair 7 additionally shows a selective green/yellow-green-to-ochre and blue-to-cyan relationship; keep that as the source-gated `documentary-earth` subprofile rather than forcing it onto street and shop scenes.

The composites also contain visible grain, dust, softness, and possible local-contrast changes. Exclude grain, dust, blur, and local contrast from recipe learning. v0.3.4 may use the measured crisp-edge tendency of pairs 1–4 only through the optional explicit `documentary-vivid-refine.json` output-sharpen preset; see [texture-refinement.md](texture-refinement.md).

## Generic route

For generic `经典纪实`, `纪实摄影调色`, `彩色纪实`, or equivalent documentary-color language, return two standard color-only variants:

- `documentary-vivid`: dense, vivid color for low-contrast landscape, rural, travel, autumn, field, storm, or coastal scenes;
- `documentary-archive`: softened print color for street, urban, humanist, shop, harbor, grassland, or everyday scenes.

If the generic prompt also contains an unambiguous scene term, select the corresponding profile. Otherwise render both with `variants.py`; do not average them into one recipe. A named profile cue outranks the generic route.

Route explicit grassland, pastoral, steppe, earth, or ochre documentary language to `documentary-earth`. Its hue ranges are source-color selections, not semantic land, grass, or sky masks; disclose that similarly colored pixels may move together.

When the source is a bright green grassland but the intended earth result is measurably denser, keep the selective earth look shared and place the measured exposure reduction in source-specific correction. In the study pair, approximately `-0.25..-0.40 EV` improved tone and global-color agreement; use that range only when the source percentiles support it.

## Source-analysis overrides

- Reduce the vivid baseline when the source already has deep shadows or extreme saturation; do not chase the sample's strongest delta into clipping.
- Prefer the archive baseline when the source already has strong local contrast or the user values a quiet humanist mood.
- For an already balanced, high-contrast street or shop source, derive the conservative archive variant instead of forcing the standard baseline.
- For a high-key, cool-dominant harbor or open-sky source whose intended archive result is measurably denser, keep the archive look shared but place the measured `-0.30..-0.45 EV` adjustment in source-specific correction. Raise muted-color vibrance only when saturation percentiles show that the target expands muted color without expanding the P95 peak. Do not hard-code this correction into the reusable look.
- Keep vivid signature colors such as a yellow vehicle, autumn foliage, painted signage, or warm wood unless preview inspection shows clipping or fluorescence.
- Disable heuristic skin protection only after visual inspection confirms that the scene has no people or that the mask is overbroad.

## Effect boundary

All default documentary profiles must omit `effects` and `texture`. Report grain, dust, vignette, blur, light leak, clarity, dehaze, denoise, and repair as unsupported. Treat an explicit sharpening/output-sharpening request separately: after source inspection, optionally use schema 1.3 `documentary-vivid-refine.json`; never infer it from `经典纪实`, `档案`, or a reference alone. Do not simulate unsupported texture with source glow. The label `档案` describes tonal and chromatic relationships only.
