# Wabi-sabi deep gray

Use this reference for prompts containing `侘寂`, `侘寂深灰`, `深黑灰`, `沥青灰`, dark minimalist interiors, a dark-overlay metaphor, warm material accents against restrained cool surroundings, or closely equivalent language.

## Translate the style into a treatment contract

- **Base tone:** low-key deep neutral-to-cool gray, closer to asphalt than blue-black.
- **Exposure:** visibly lower than the source when requested, but never implement a literal black overlay.
- **Shadows:** deep near-black gray with barely retained texture and object boundaries; reject featureless dead black unless the encoded source was already clipped.
- **Midtones:** compact, cool asphalt gray with decisive separation from shadows.
- **Highlights:** restrained and unclipped; allow small milk-white, pale clay, or warm neutral accents to remain soft rather than brilliant.
- **Color hierarchy:** keep black, white, and gray neutral; retain red, orange, amber, yellow, wood, ochre, and brown as the comparatively warmer and more chromatic focal family; push unrelated cool and miscellaneous colors toward lower chroma.
- **Light character:** interpret `硬光`, `利落`, or `通透` as firm tonal separation using allowed curves and channel controls. Preserve the position, shape, and size of every source highlight.
- **Surface character:** keep the source clean and grain-free. Never add grain, clarity, sharpening, dehaze, local contrast, denoising, smoothing, or texture synthesis.
- **Effects:** keep absent unless the user separately requests source-derived highlight diffusion and explicitly approves it. This style normally needs no diffusion.

## Interpret common phrases honestly

- Treat `像覆盖了 50% 黑色图层` as a visual metaphor for lower exposure, compressed midtones, and a deep-gray base. Do not composite an overlay.
- Treat `暗部信息压低至极限` as permission to approach the near-black warning boundary, not to erase recoverable texture. Keep a narrow but visible separation among black, charcoal, and asphalt-gray regions.
- Treat `主体和环境不发黄` as neutralizing a global yellow cast. It does not mean removing the deliberately retained warm focal colors.
- Treat `暖色饱和度与明亮度显著高于冷色` as a relative hierarchy. Do not make warm colors fluorescent or drive warm highlights into clipping.
- Treat `原生小光比` as source-light placement language. Do not invent relighting, rim light, rays, or new reflections.
- If the user also explicitly requests output sharpening, keep it separate from the style decision. Inspect the source first and use the schema 1.3 bounded refine path only when the image is already focused; otherwise retain the color-only treatment and explain that repair is unsupported.

## Authoring guidance

Start with `assets/recipes/wabi-sabi-deep-gray.json`. Treat it as a source-safe standard color baseline, not a universal exposure correction. Promote it to bold only after source analysis supports deeper tonal movement.

1. Inspect source clipping and subject visibility before lowering exposure further.
2. Keep the preset's skin heuristic disabled until visual inspection confirms people are present and warm non-skin materials will not be overprotected.
3. Adjust correction exposure first when the entire frame is too bright or too dark.
4. Adjust the tone curve second when shadow-to-midtone separation is weak.
5. Adjust the cool-family hue range only when non-focal colors remain too prominent.
6. Adjust the warm-family range only when the intended focal material no longer separates from the gray base.
7. Change one axis per revision and stop before shadows become featureless or highlights clip.

When source near-black coverage already exceeds 20%, keep `exposure_ev` near zero and set a positive S-curve only when the preview keeps the near-black increase within the ordinary warning allowance. Build the style primarily through color hierarchy and controlled highlights instead of crushing an already dark source.

Keep the warm and cool hue ranges broadly feathered. They select source pixel colors, not wood, pottery, walls, water, or other semantic objects. Similar colors elsewhere in the image may move together; disclose that limitation when it matters.

Use `bold` when the prompt mainly describes a pronounced dark-gray look. Use `transformative` only when the user explicitly requests a radical tonal-hierarchy change or accepts substantially more near-black coverage. Do not infer transformative from `侘寂` alone.

## Preview acceptance

Accept the preview only when all of the following are visually true:

- the overall image reads as deep charcoal/asphalt gray rather than yellow-brown or blue-black;
- the subject remains legible without lifting the entire frame;
- warm focal colors remain clearly more chromatic and luminous than cool miscellaneous colors;
- small highlights remain controlled and non-clipped;
- shadow texture is faint but present at 100% inspection;
- no sharpening halo, synthetic grain, new light shape, or literal overlay appears.
