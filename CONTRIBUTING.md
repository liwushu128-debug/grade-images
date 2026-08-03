# Contributing

Thank you for improving `grade-images`.

## Principles

Changes must preserve the project's central contract: color and tone may change, while geometry, identity, objects, and source texture remain structurally untouched.

Do not add crop, resize, warp, inpainting, generative editing, face restoration, skin smoothing, blur, sharpen, denoise, clarity, grain, or arbitrary executable filter operations to strict mode.

## Development setup

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m compileall -q skills/grade-images/scripts
```

Use Python 3.10 or newer. Keep runtime dependencies limited to Pillow and NumPy unless a new dependency has a clear safety and portability benefit.

## Pull requests

Keep each pull request focused. Explain:

- the user-visible problem;
- why the change belongs in a reusable skill;
- how preservation behavior is affected;
- which automated and visual tests were run;
- any remaining warnings or unsupported cases.

Add regression coverage for every bug fix. New recipe fields must fail closed in old validators, be documented in `references/recipe-schema.md`, and include range validation before renderer support is added.

Do not commit private photographs, generated test outputs, local dependency folders, or files without a clear redistribution license. Small test assets added to the repository must include source and license provenance.

## Review checklist

- Inputs are never overwritten.
- Unknown recipe keys still fail closed.
- Dimensions and alpha topology remain unchanged.
- Rendering remains deterministic for identical inputs and recipes.
- ICC behavior and output profile claims remain accurate.
- No new texture, geometry, or generative operation is introduced.
- Unit tests and representative visual QA pass.
- `SKILL.md` remains concise and repository documentation stays outside the skill folder.

By submitting a contribution, you agree that it is licensed under Apache-2.0, consistent with the repository license.

