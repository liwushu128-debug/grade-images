# Grade Images

`grade-images` is a deterministic Codex skill for photographic color correction, reference matching, creative color grading, batch consistency, and explicitly approved source-derived highlight diffusion. It never uses a generative image editor.

The core design is simple: let the AI interpret intent and review previews, then let a constrained local renderer execute a versioned JSON recipe.

## 中文简介

`grade-images` 是一个面向 Codex 的确定性照片调色技能，支持曝光与白平衡校正、参考图匹配、创意调色、批量风格统一，以及经用户明确许可的原生高光扩散。它不调用生成式图像编辑器，而是由 AI 理解审美意图、审阅预览，再通过受约束的本地渲染器执行可复现、可审计的版本化 JSON 配方。

技能以保护原图内容为核心：不会改变尺寸、几何结构、人物五官、物体、文字或纹理，也不会凭空合成光源、光束、镜头光斑等效果。即使选择强烈调色，仍会将色彩强度与光效权限分开；只有在用户明确同意后，才允许从原图真实高光中提取并生成受控的柔和扩散。

v0.2.1 新增多方案预览与带原图的标注对比图，可从一个基础配方自动派生保守、标准和强烈三档，同时确保校正、保护设置和光效权限保持不变。参考匹配被细分为阴影、中间调、高光以及不同色彩浓度区间；在用户选定强度后，还能在该档内部搜索多个安全候选。质量报告会分别呈现色调、色彩浓度、全局色偏和亮度分区色彩的匹配进度，在未达目标时给出下一项可执行调整建议。开发者还可通过本地回归清单测试双向转换，同时让私有测试照片始终留在仓库之外。

v0.3.0 加入“变革型”调色：当用户明确要求大幅改变整体色调、显著压低某类颜色或把一种颜色家族转向另一种颜色时，技能不再受以往保守审美幅度限制。新的 schema 1.2 可依据原图像素的色相、饱和度和明度进行平滑范围重映射，例如把暖白樱花推向浅紫，同时压低环境黄橙。它仍不使用语义分割、生成式蒙版或合成光效，尺寸、五官、物体、文字、纹理与原生光线位置继续受到严格保护。

## Why this skill exists

Many image-editing workflows mix color decisions with generative reconstruction. That can subtly change faces, objects, texture, or geometry. This skill instead uses an operation whitelist and an engine that has no crop, warp, inpainting, sharpening, smoothing, denoising, or synthesis operators.

Strict mode guarantees that the pipeline cannot intentionally:

- alter image dimensions or alpha topology;
- reshape faces or objects;
- add, remove, or regenerate scene content;
- sharpen, blur the source image, denoise, smooth skin, or synthesize texture;
- synthesize or composite suns, lamps, reflections, flares, starbursts, halos, rays, rim lights, or painted highlights;
- execute unknown recipe operations.

Color grading necessarily changes pixel values. JPEG re-encoding is also lossy. The skill therefore guarantees constrained operations and structural preservation, not byte-identical output.

## Features

- Exposure and white-balance correction in linear light, separated from aesthetic intensity.
- Explicit conservative, standard, bold, and transformative strategies; standard is the fallback when a subjective request has no chosen intensity.
- Reproducible creative looks using monotonic curves, ASC-CDL-style controls, saturation, and restrained split toning.
- Schema 1.1 vibrance for strong color changes without uniformly overdriving already-saturated regions.
- Schema 1.2 smooth hue-range remapping with source hue, saturation, and luminance gates—without semantic or generated masks.
- Reference-derived matching without neural style transfer.
- Labeled multi-variant previews that retain every independent result and recipe.
- A single-pass preview command that renders, evaluates, labels, and records timings without repeated image decoding or ad hoc sheet scripts.
- Automatic conservative/standard/bold/transformative derivation that scales only the creative look.
- Shadow/midtone/highlight-aware reference diagnostics with actionable next adjustments.
- Safety-gated reference candidate search contained within the user-selected intensity.
- Per-image batch normalization followed by one shared creative look.
- Optional feathered skin-color protection with explicit uncertainty warnings.
- Embedded ICC conversion to an sRGB working and output space.
- Machine-readable recipes, render manifests, and quality reports.
- Structural alarms for changed dimensions, alpha topology, edge orientation, new edges, clipping, and extreme saturation.
- Optional source-derived highlight glow after explicit consent, with strict rejection of synthetic lighting.
- Reference-aware distribution checks that keep structural safety separate from aesthetic target matching.
- An opt-in local regression runner that keeps private test photographs outside the repository.

## Supported scope

Version 0.3.0 accepts single-frame, 8-bit JPEG and PNG images. It intentionally does not support RAW files, video, animated images, 16-bit images, retouching, geometry changes, grain, denoising, sharpening, synthetic/composited lighting, or generative edits.

Fully clipped highlights or shadows in an encoded JPEG or PNG cannot be recovered.

## Install

Requirements:

- Python 3.10 or newer;
- Pillow;
- NumPy.

From a repository checkout, install the runtime dependencies:

```bash
python -m pip install -r requirements.txt
```

Copy `skills/grade-images` into the Codex skills directory. The usual destination is `$CODEX_HOME/skills/grade-images`; when `CODEX_HOME` is unset, use `~/.codex/skills/grade-images`.

macOS or Linux:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/grade-images "${CODEX_HOME:-$HOME/.codex}/skills/grade-images"
```

Windows PowerShell:

```powershell
$codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
New-Item -ItemType Directory -Force (Join-Path $codexRoot 'skills') | Out-Null
Copy-Item -Recurse -Force 'skills\grade-images' (Join-Path $codexRoot 'skills\grade-images')
```

Restart Codex after installing or updating the skill.

## Use

Ask Codex naturally, for example:

- “Correct the exposure and white balance without changing texture or facial features.”
- “Match this photo to the reference image's color treatment.”
- “Give this set a cohesive restrained cinematic grade.”
- “Audit these photos for clipping and color-cast problems.”

The skill supports five workflows: `audit`, `correct`, `look`, `match`, and `batch`.

For a subjective look, choose `conservative`, `standard`, `bold`, or `transformative`. If the prompt does not imply one, the skill asks before rendering; if no answer is available, it uses standard rather than silently weakening the grade. Style words such as `natural` and `cinematic` do not imply desaturation. Transformative is selected only by an explicit major-change instruction or direct user choice.

Direct script usage is also available from `skills/grade-images`:

```bash
python scripts/analyze.py input.jpg --output analysis.json
python scripts/grade.py validate assets/recipes/neutral-correction.json
python scripts/grade.py render input.jpg --recipe assets/recipes/muted-cinematic.json --output preview.png --max-size 1600
python scripts/compare.py input.jpg preview.png --recipe assets/recipes/muted-cinematic.json --output quality.json
python scripts/compare.py input.jpg preview.png --recipe match.json --reference reference.jpg --output quality.json
python scripts/preview.py input.jpg --recipe assets/recipes/transformative-cool-violet.json --output-dir previews --max-size 1200
python scripts/variants.py input.jpg --variant conservative=a.json --variant standard=b.json --variant bold=c.json --variant transformative=d.json --output-dir previews
python scripts/variants.py input.jpg --base-recipe base.json --output-dir previews
python scripts/search_match.py input.jpg reference.jpg --template assets/recipes/neutral-correction.json --intensity bold --output-dir match-search
python scripts/regress.py private-cases.json --output-dir regression-results
```

Before a subjective render, Codex briefly states the intended tonal direction, color direction, intensity, preservation choices, and effect status. If several interpretations remain plausible, the variants command produces individual previews plus a labeled sheet containing the original. Reference reports separate tone, chroma, global color, and tonal-zone color progress, then suggest the next measured adjustment.

For a single subjective result, `preview.py` is the preferred fast path: it produces the preview image, copied recipe, quality report, labeled comparison sheet, manifest, and stage timings in one process. A matching bundled preset is rendered before Codex authors a recipe from scratch; quality thresholds must not be chased by changing unrelated exposure or color axes.

For low-light scenes, start with `assets/recipes/low-light-cinematic.json`. For scenes without people, or when the heuristic mask is visibly overbroad, disable skin protection during match or batch recipe generation.

Use `assets/recipes/natural-standard.json` for a believable but visibly improved natural starting point, `assets/recipes/bold-cinematic.json` for an unmistakable creative starting point, and `assets/recipes/transformative-cool-violet.json` for an explicit warm-to-pale-violet transformation.

For dreamlike, soft-glow, sacred-light, or hazy requests, intensity does not imply effect permission. The skill first asks whether restrained source-derived highlight diffusion is allowed. After explicit approval, `assets/recipes/soft-dream-source-glow.json` is available as a starting point. The effect only spreads light already present in the source and cannot add a light source, flare, ray, starburst, or new scene content.

## Output contract

A completed render produces:

- the graded image;
- an exact copy of the JSON recipe;
- a manifest containing source and output hashes;
- a machine-readable quality report when comparison is run.

Input files are never overwritten. Prefer PNG for a lossless graded master and create a JPEG derivative only when required.

## Develop

Install development dependencies and run the test suite:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m compileall -q skills/grade-images/scripts
```

Build a deterministic release archive:

```bash
python tools/package_skill.py --output dist/grade-images.zip
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution rules and the preservation constraints that changes must respect.

## License

Apache License 2.0. See [LICENSE](LICENSE).
