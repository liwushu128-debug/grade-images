# Semantic intent and scene routing

Use scene routing before enabling skin protection or when a warm scene could
confuse skin-color heuristics. The router records evidence; it does not detect
faces, identify people, or grant new pixel operations.

Run:

```text
python scripts/route_scene.py INPUT "PROMPT" \
  --people-evidence present|absent|unknown --output route.json
```

Choose `people-evidence` from visual inspection. Use `unknown` when inspection
cannot establish whether a person is present. Never infer `present` from the
skin-color mask itself.

The output separates:

- prompt-derived intensity and style;
- effect cues from explicit effect permission;
- texture permission from visual style;
- source measurements from scene evidence;
- the skin-protection routing decision and its reason.

Follow the skin decision as a recipe-authoring recommendation:

- `enable`: people are visibly present and the candidate region is spatially bounded;
- `disable`: no people are present, candidates are absent, or a broad warm region is likely;
- `review`: color-and-space evidence is insufficient, so inspect before deciding.

The route file never overrides an explicit current user instruction, and it
does not change the renderer whitelist. Keep it beside the recipe when its
evidence affected protection settings.
