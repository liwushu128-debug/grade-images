# Film color routing

## Scope

Interpret film-language as a tone-and-color request under strict preservation. Do not infer grain, vignette, blur, light leak, distortion, sharpening, crop, or another texture or geometry operation from `胶片感`, `film look`, or a named film-color family.

Run the deterministic router before authoring a film-color recipe:

```text
python scripts/route_film.py "PROMPT" [--output route.json]
```

The router does not inspect pixels and does not render. Use its candidates only after normal source analysis. Keep source correction separate from the selected creative look.

## Generic prompts

For a generic prompt such as `胶片感`, `胶片风格`, or `film look`, return three standard-intensity color-only directions:

- `classic-negative`: soft highlight separation, earthy warm midtones, and restrained cool undertones;
- `daylight-disposable`: punchy daylight snapshot color, lively greens, and warm highlights;
- `cinematic-print`: dense midtones, cool shadows, warm highlights, and restrained print-like chroma.

Use `variants.py` to show these directions together when the user has not supplied a more specific cue. Do not collapse them into one averaged recipe. If continuing without a choice is appropriate, use `classic-negative-standard.json` as the broadest baseline, state that standard intensity was used, and still keep effects absent.

## Specific prompts

- Route `一次性胶片`, `一次性相机`, daylight snapshot, outdoor foliage, party, or flash-snapshot language to `daylight-disposable-standard.json`.
- Route `经典负片`, `彩色负片`, soft negative, portrait, everyday, or street language to `classic-negative-standard.json`.
- Route `电影胶片`, `电影印片`, film print, night, interior, or narrative language to `cinematic-print-standard.json`.

Specific profile terms outrank generic film terms. Scene terms refine a specific match but must not select a profile by themselves when the prompt contains no film-color request.

## Effect boundary

If the prompt also requests grain, vignette, blur, light leak, distortion, clarity, dehaze, denoise, repair, or generated detail, report that request separately as unsupported. Treat an explicit sharpening/output-sharpening request as a separate schema 1.3 candidate only after source review; do not infer it from film language or enable it automatically. Do not enable source glow as a substitute.

All bundled film-color recipes must:

- omit `effects`;
- retain the exact strict preservation object;
- use only whitelisted correction and look operations;
- retain dimensions, alpha topology, edges, and source texture;
- validate and remain deterministic across the bundled synthetic scene matrix.
