# Grade Images

`grade-images` is a deterministic Codex skill for camera RAW development, photographic color correction, reference matching, creative color grading, batch consistency, explicitly approved source-derived highlight diffusion, and opt-in bounded output sharpening. It never uses a generative image editor.

The core design is simple: let the AI interpret intent and review previews, then let a constrained local renderer execute a versioned JSON recipe.

## 中文简介

`grade-images` 是一个面向 Codex 的确定性照片调色技能，支持曝光与白平衡校正、参考图匹配、创意调色、批量风格统一，以及经用户明确许可的原生高光扩散。它不调用生成式图像编辑器，而是由 AI 理解审美意图、审阅预览，再通过受约束的本地渲染器执行可复现、可审计的版本化 JSON 配方。

技能以保护原图内容为核心：不会改变尺寸、几何结构、人物五官、物体、文字或纹理，也不会凭空合成光源、光束、镜头光斑等效果。即使选择强烈调色，仍会将色彩强度与光效权限分开；只有在用户明确同意后，才允许从原图真实高光中提取并生成受控的柔和扩散。

v0.2.1 新增多方案预览与带原图的标注对比图，可从一个基础配方自动派生保守、标准和强烈三档，同时确保校正、保护设置和光效权限保持不变。参考匹配被细分为阴影、中间调、高光以及不同色彩浓度区间；在用户选定强度后，还能在该档内部搜索多个安全候选。质量报告会分别呈现色调、色彩浓度、全局色偏和亮度分区色彩的匹配进度，在未达目标时给出下一项可执行调整建议。开发者还可通过本地回归清单测试双向转换，同时让私有测试照片始终留在仓库之外。

v0.3.0 加入“变革型”调色：当用户明确要求大幅改变整体色调、显著压低某类颜色或把一种颜色家族转向另一种颜色时，技能不再受以往保守审美幅度限制。新的 schema 1.2 可依据原图像素的色相、饱和度和明度进行平滑范围重映射，例如把暖白樱花推向浅紫，同时压低环境黄橙。它仍不使用语义分割、生成式蒙版或合成光效，尺寸、五官、物体、文字、纹理与原生光线位置继续受到严格保护。

v0.3.1 聚焦稳定性、速度、RAW 开发与风格语言扩展。多个色相范围现在统一依据同一份不可变源颜色状态计算，并以顺序无关的方式合成，避免调整配方数组顺序就改变画面。预览与候选图使用更快的无损 PNG 编码，而最终渲染继续保留原有输出质量。RAW 路径显式锁定 AHD 去马赛克、相机白平衡、sRGB 输出和无自动提亮开发，并明确关闭降噪、坏点修复、中值滤波、色差校正、锐化等细节处理，同时把完整参数写入清单。本版本还新增“侘寂深灰”参考与预设，可构建沥青深灰基底、受控高光、低饱和冷色环境和相对突出的暖色主体，同时仍禁止真实黑色图层、锐化、颗粒与合成光效。

v0.3.2 是 RAW 优化版本。相机白平衡不再只按“系数为正”粗略判定：缺失、非法或可疑的单位系数会被分别记录，并按固定规则回退到有效日光系数或解码器默认值，避免把无效元数据误报成 as-shot 白平衡。`raw_check.py --require-camera-wb` 可在严格工作流中拒绝任何回退。最终 RAW PNG 改用更快的无损压缩级别，渲染清单新增开发、调色、保存和哈希阶段耗时、输出编码参数、方向标记与完整白平衡来源，便于定位兼容性和性能问题。真实 NEF、ARW 与 DNG 被纳入本地回归覆盖，原始文件仍不会写入发布包。

v0.3.3 新增严格的胶片色彩路由。`route_film.py` 将通用“胶片感”拆成经典负片、日光一次性胶片与电影印片三种可比较方向，并把更具体的提示词确定性地路由到相应 color-only 配方。所有胶片配方继续服从严格保护：不加入颗粒、暗角、柔焦、漏光、畸变、锐化或裁切；当提示词要求这些效果时，路由器会单独报告为不支持，而不是静默启用。v0.3.2 的 RAW 白平衡、性能诊断和真实 NEF/ARW/DNG 回归能力保持不变。

The v0.3.3 documentary extension adds `route_documentary.py` and two color-only baselines learned from eight local Before/After study pairs: vivid documentary and archival documentary. The private examples are not packaged. Grain, dust, vignette, blur, light leaks, sharpening, clarity, dehaze, crop, and geometry changes remain forbidden.

Version 0.3.4 keeps every ordinary recipe color-only and pixel-compatible with v0.3.3, then adds one schema 1.3 refinement path for an explicit current request for output sharpening. The only new operator is bounded, source-derived luminance sharpening after resize, with skin/noise protection and texture alarms. It cannot denoise, deblur, restore, super-resolve, add clarity/dehaze/local contrast, synthesize grain, repair defects, or generate content.

## Why this skill exists

Many image-editing workflows mix color decisions with generative reconstruction. That can subtly change faces, objects, texture, or geometry. This skill instead uses an operation whitelist and an engine that has no crop, warp, inpainting, smoothing, denoising, restoration, or synthesis operators. Its sole texture operator is explicitly requested, bounded output sharpening of existing luminance detail.

Strict mode guarantees that the pipeline cannot intentionally:

- alter image dimensions or alpha topology;
- reshape faces or objects;
- add, remove, or regenerate scene content;
- alter texture by default, blur the source image, denoise, smooth skin, repair detail, or synthesize texture;
- synthesize or composite suns, lamps, reflections, flares, starbursts, halos, rays, rim lights, or painted highlights;
- execute unknown recipe operations.

Color grading necessarily changes pixel values. JPEG re-encoding is also lossy. The skill therefore guarantees constrained operations and structural preservation, not byte-identical output.

## Features

- Exposure and white-balance correction in linear light, separated from aesthetic intensity.
- Explicit conservative, standard, bold, and transformative strategies; standard is the fallback when a subjective request has no chosen intensity.
- Reproducible creative looks using monotonic curves, ASC-CDL-style controls, saturation, and restrained split toning.
- Schema 1.1 vibrance for strong color changes without uniformly overdriving already-saturated regions.
- Schema 1.2 smooth hue-range remapping with source hue, saturation, and luminance gates—without semantic or generated masks.
- A documented wabi-sabi deep-gray treatment with an asphalt-charcoal base, restrained cool colors, warmer focal accents, controlled highlights, and no literal overlays or sharpening.
- Reference-derived matching without neural style transfer.
- Labeled multi-variant previews that retain every independent result and recipe.
- A single-pass preview command that renders, evaluates, labels, and records timings without repeated image decoding or ad hoc sheet scripts.
- Automatic conservative/standard/bold/transformative derivation that scales only the creative look.
- Shadow/midtone/highlight-aware reference diagnostics with actionable next adjustments.
- Safety-gated reference candidate search contained within the user-selected intensity.
- Per-image batch normalization followed by one shared creative look.
- Optional feathered skin-color protection with explicit uncertainty warnings.
- Embedded ICC conversion to an sRGB working and output space.
- Optional rawpy/LibRaw camera RAW and DNG development with explicit AHD demosaicing, validated camera/daylight white-balance routing, disabled detail operations, and recorded bit-depth, color-space, orientation, and decoder settings.
- Machine-readable recipes, render manifests, and quality reports.
- Structural alarms for changed dimensions, alpha topology, edge orientation, new edges, clipping, and extreme saturation.
- Optional source-derived highlight glow after explicit consent, with strict rejection of synthetic lighting.
- Reference-aware distribution checks that keep structural safety separate from aesthetic target matching.
- An opt-in local regression runner that keeps private test photographs outside the repository.

## Supported scope

Version 0.3.4 accepts single-frame, 8-bit JPEG and PNG images plus camera RAW and DNG files supported by the installed rawpy/LibRaw backend. RAW support is optional, uses a 16-bit decoder intermediate for full development, and currently exports an 8-bit PNG or JPEG derivative; it never rewrites a camera RAW. Video, animated images, encoded 16-bit raster inputs, retouching, geometry changes, grain, denoising, deblurring, restoration, synthetic/composited lighting, and generative edits remain unsupported. Output sharpening is available only through an explicit schema 1.3 refinement request.

Fully clipped highlights or shadows in an encoded JPEG or PNG cannot be recovered.

## Install

Requirements:

- Python 3.10 or newer;
- Pillow;
- NumPy.

Camera RAW additionally requires rawpy/LibRaw.

From a repository checkout, install the runtime dependencies:

```bash
python -m pip install -r requirements.txt
```

For camera RAW and DNG input, install the optional backend:

```bash
python -m pip install -r requirements-raw.txt
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
python scripts/raw_check.py input.nef --output raw-check.json --full-decode
python scripts/raw_check.py input.nef --output raw-check.json --require-camera-wb
python scripts/grade.py validate assets/recipes/neutral-correction.json
python scripts/grade.py render input.jpg --recipe assets/recipes/muted-cinematic.json --output preview.png --max-size 1600
python scripts/compare.py input.jpg preview.png --recipe assets/recipes/muted-cinematic.json --output quality.json
python scripts/compare.py input.jpg preview.png --recipe match.json --reference reference.jpg --output quality.json
python scripts/preview.py input.jpg --recipe assets/recipes/transformative-cool-violet.json --output-dir previews --max-size 1200
python scripts/route_film.py "标准强度胶片感" --output film-route.json
python scripts/route_documentary.py "经典纪实摄影调色" --output documentary-route.json
python scripts/variants.py input.jpg --variant conservative=a.json --variant standard=b.json --variant bold=c.json --variant transformative=d.json --output-dir previews
python scripts/variants.py input.jpg --base-recipe base.json --output-dir previews
python scripts/search_match.py input.jpg reference.jpg --template assets/recipes/neutral-correction.json --intensity bold --output-dir match-search
python scripts/regress.py private-cases.json --output-dir regression-results
```

Before a subjective render, Codex briefly states the intended tonal direction, color direction, intensity, preservation choices, and effect status. If several interpretations remain plausible, the variants command produces individual previews plus a labeled sheet containing the original. Reference reports separate tone, chroma, global color, and tonal-zone color progress, then suggest the next measured adjustment.

For a single subjective result, `preview.py` is the preferred fast path: it produces the preview image, copied recipe, quality report, labeled comparison sheet, manifest, and stage timings in one process. A matching bundled preset is rendered before Codex authors a recipe from scratch; quality thresholds must not be chased by changing unrelated exposure or color axes.

For low-light scenes, start with `assets/recipes/low-light-cinematic.json`. For scenes without people, or when the heuristic mask is visibly overbroad, disable skin protection during match or batch recipe generation.

Use `assets/recipes/natural-standard.json` for a believable but visibly improved natural starting point, `assets/recipes/bold-cinematic.json` for an unmistakable creative starting point, and `assets/recipes/transformative-cool-violet.json` for an explicit warm-to-pale-violet transformation.

Use `assets/recipes/wabi-sabi-deep-gray.json` when the requested look calls for low exposure, deep charcoal or asphalt-gray tonal placement, restrained cool and miscellaneous colors, and comparatively warmer wood, clay, amber, red, orange, or yellow focal accents. Dark-overlay language is interpreted as a tonal target; the renderer does not composite an overlay. Keep this color-only unless the user separately and explicitly requests bounded output sharpening and the source passes texture preflight; clarity remains unsupported.

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
