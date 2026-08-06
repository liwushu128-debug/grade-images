# RAW processing contract

## Scope

Use the optional `rawpy/LibRaw` backend for camera RAW and DNG inputs. Format support depends on the bundled LibRaw version and the exact camera/compression variant; a familiar suffix is not proof that a file is decodable.

Install the optional backend from the repository root:

```text
python -m pip install -r requirements-raw.txt
```

For an already copied or extracted skill, run the same command against `requirements-raw.txt` inside the `grade-images` skill directory.

After installation, validate one or more real camera files without rendering a look:

```text
python scripts/raw_check.py INPUT.NEF [INPUT.DNG ...] --output raw-check.json --full-decode
```

The check decodes the bounded preview twice, requires identical pixels and development metadata, verifies the source hash, and optionally performs one 16-bit full decode.

Add `--require-camera-wb` when the workflow must fail instead of using a deterministic white-balance fallback. Without that flag, a fallback is reported with its reason and remains a warning for visual review.

If the backend is absent or rejects the file, stop with the decoder error. Do not silently grade an embedded JPEG thumbnail, rename the file, or route it through a generative editor.

## Deterministic baseline

Decode with these fixed decisions:

- classify camera/as-shot coefficients as `valid`, `missing`, `invalid`, or `identity_suspect`; equal RGB coefficients such as `[1, 1, 1, 1]` are not accepted as trustworthy as-shot metadata;
- use valid camera/as-shot white balance first, otherwise use valid daylight coefficients, otherwise retain LibRaw's deterministic default behavior;
- disable automatic white balance;
- disable automatic brightness;
- explicitly use AHD demosaicing so the full-resolution path does not inherit a changing library default;
- convert through LibRaw to sRGB;
- use a 16-bit decoder output for full-resolution development and an 8-bit decoder output for bounded previews;
- use the standard sRGB transfer parameters `(2.4, 12.92)`;
- keep highlight mode at `clip`; do not reconstruct colors beyond recorded sensor channels;
- explicitly disable four-color interpolation, DCB enhancement, FBDD denoise, noise-threshold filtering, median filtering, bad-pixel repair, chromatic-aberration correction, sharpening, and other detail operations;
- respect the recorded orientation;
- use half-size demosaicing only when the requested preview is smaller than half the visible RAW dimensions, then resize once to the requested bound.

Record rawpy and LibRaw versions, camera and daylight white-balance values and statuses, selected source and fallback reason, orientation, bit depth, half-size choice, highlight mode, and disabled automatic/detail operations in `raw_development` inside analysis and render manifests.

The current renderer performs the grade from the 16-bit-derived floating-point array but exports an 8-bit PNG or JPEG derivative. Do not describe the derivative as a 16-bit master.

## Interpretation

Treat RAW development and creative grading as separate stages. First inspect the deterministic neutral development. Then apply the same correction/look/effect recipe used for encoded photographs.

Camera white balance is metadata, not ground truth. Missing, invalid, or suspicious identity coefficients trigger a recorded deterministic fallback; automatic white balance remains disabled. If the fallback or the developed preview is visibly implausible, request a neutral target or explicit temperature/tint direction before creative grading.

RAW can retain highlight or shadow information absent from an accompanying JPEG, but it does not guarantee recoverable detail. Do not use highlight reconstruction, local tone recovery, denoise, lens correction, or defect repair. The LibRaw development stage remains unsharpened. After development and grading, schema 1.3 may apply bounded output sharpening only when the user explicitly requests it; never describe that as RAW detail recovery.

## Output and metadata

Never overwrite the RAW source. Export PNG or JPEG only; do not write a modified camera RAW or DNG.

Describe a PNG as a lossless graded derivative of the recorded demosaiced RGB development. It is not a lossless representation of the sensor mosaic. Maker-specific EXIF, focus data, lens corrections, previews, and proprietary edit instructions may not survive; retain the untouched RAW and the generated manifest as the authoritative provenance pair.

For RAW-to-PNG final renders, the renderer uses PNG compression level 2. This changes file size and encoding time, not decoded pixels. The render manifest records this setting plus input hashing, RAW development, grading, saving, and output hashing durations so performance bottlenecks can be distinguished.
