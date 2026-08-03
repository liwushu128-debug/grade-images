# Recipe schema

## Top-level structure

Every recipe is JSON with these allowed keys:

- `schema_version`: must be `1.0`.
- `intent`: short human-readable explanation.
- `strategy`: selected aesthetic strategy and how it was selected.
- `preservation`: strict execution policy.
- `correction`: source-specific technical correction.
- `look`: reusable creative treatment.
- `protection`: protected-region settings.
- `output`: encoding settings.

Unknown keys fail validation.

## Strategy

Use this optional object for new recipes:

```json
{
  "intensity": "standard",
  "style": "natural",
  "selection": "explicit"
}
```

- `intensity`: `conservative`, `standard`, or `bold`.
- `style`: `technical`, `natural`, `cinematic`, `reference`, or `custom`.
- `selection`: `explicit`, `inferred`, `default-standard`, or `template`.

This field records the decision; it does not weaken strict preservation. Legacy recipes without it remain valid.

## Preservation

```json
{
  "mode": "strict",
  "allow_geometry_changes": false,
  "allow_texture_changes": false,
  "allow_generative_changes": false
}
```

All four values are mandatory in v0.1 and must match the example exactly.

## Correction

Allowed keys and ranges:

- `exposure_ev`: `-3.0..3.0`
- `white_balance.rgb_gains`: three values in `0.5..2.0`
- `black_point`: `0.0..0.2`
- `white_point`: `0.8..1.5`, greater than `black_point`
- `highlight_rolloff`: `0.0..1.0`

Prefer explicit RGB gains over ambiguous Kelvin values. Record how the gains were chosen in `intent` or the surrounding quality report.

## Look

Allowed keys and ranges:

- `tone_curve.strength`: `-1.0..1.0`; positive values create a safe S-curve, negative values soften contrast.
- `cdl.slope`: three values in `0.25..4.0`
- `cdl.offset`: three values in `-0.25..0.25`
- `cdl.power`: three values in `0.25..4.0`
- `cdl.saturation`: `0.0..2.0`
- `saturation`: `0.0..2.0`
- `split_tone.shadows`: RGB triplet in `0.0..1.0`
- `split_tone.highlights`: RGB triplet in `0.0..1.0`
- `split_tone.balance`: `-1.0..1.0`
- `split_tone.strength`: `0.0..0.25`

The renderer applies correction before look.

The renderer multiplies `cdl.saturation` and `saturation`. To prevent an accidental double reduction or boost, set only one of them away from `1.0`; validation rejects recipes that adjust both. Treat natural color as a hue/white-balance goal, not as a request to desaturate.

## Protection

```json
{
  "skin": {
    "enabled": true,
    "strength": 0.7
  }
}
```

`strength` is `0.0..1.0` and controls how much of the grade is removed in high-confidence skin regions. Disable skin protection for images without people when visual inspection confirms that choice.

## Output

Allowed keys:

- `format`: `png` or `jpeg`
- `quality`: integer `85..100`; used only for JPEG
- `profile`: currently `sRGB`
- `preserve_metadata`: boolean

The command-line output suffix must agree with `format`.
