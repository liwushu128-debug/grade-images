# Color decisions

## Working order

Apply operations in this order:

1. decode to RGB plus optional alpha and convert a valid embedded ICC profile to sRGB;
2. convert encoded sRGB values to linear-light floating point; if no profile exists, explicitly record the sRGB assumption;
3. apply source-specific correction;
4. apply the reusable creative look;
5. reduce the grade inside protected regions;
6. compress or clip to the output gamut;
7. encode once and preserve supported metadata.

## Correction versus look

Keep correction source-specific. Exposure and white balance frequently differ across a batch. Keep the creative look shared so the series has one tonal and chromatic intent.

## Parameter guidance

- Change exposure in EV with a linear-light multiplier of `2 ** exposure_ev`.
- Use explicit RGB white-balance gains and normalize their geometric mean so the adjustment does not hide an exposure change.
- Keep black/white mapping conservative for encoded images; do not force every image to use the full numeric range. Apply black/white mapping and highlight roll-off through luminance-based RGB scaling so these operations do not create colored channel clipping.
- Use monotonic tone curves so tonal ordering is not inverted.
- Treat a source near-black fraction above 20% as a low-light warning. Preview any positive S-curve carefully and default its strength to zero when it pushes near-black coverage up by more than two percentage points.
- Use highlight roll-off to compress bright values, not to claim recovery of clipped information.
- Apply CDL in linear light. Clamp negative bases before power operations.
- Scale split toning to the selected intensity while avoiding a uniform global cast. Bold grades may use stronger tonal-zone separation, but correction and look must remain distinct.
- Preserve source chroma by default for natural styles. Do not treat a high P95 saturation measurement as sufficient reason to lower global saturation; require visible clipping, hue breakage, or fluorescence.

## Batch consistency

Do not apply identical correction parameters to every image. Estimate a safe baseline per image, then apply the same look. Flag images whose lighting or gamut makes the shared look unsafe.

## Reference matching

Treat reference matching as a comparison of distributions and tonal zones, not literal pixel correspondence. Separate luminance from chroma, cap match strength, and reduce changes in protected skin regions. A reference with a different subject or lighting geometry can guide mood but cannot define a physically exact match.

Limit automatic exposure matching to `±strength` EV. This keeps a restrained cross-scene match from inheriting an unrelated reference's day/night exposure level.
