# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from grade_core import analyze_array, load_image, load_recipe


def equalized_luminance(rgb: np.ndarray) -> np.ndarray:
    # Robust normalization removes global exposure/contrast differences without
    # the quantization edges introduced by per-image histogram equalization.
    luma = np.sum(rgb * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=2)
    low, high = np.percentile(luma, [1, 99])
    return np.clip((luma - low) / max(float(high - low), 1e-6), 0.0, 1.0)


def gradient_metrics(source: np.ndarray, output: np.ndarray) -> dict[str, float]:
    src = equalized_luminance(source)
    dst = equalized_luminance(output)
    sy, sx = np.gradient(src)
    dy, dx = np.gradient(dst)
    sm = np.hypot(sx, sy)
    dm = np.hypot(dx, dy)
    # Do not promote ordinary smooth gradients into edges merely because they
    # occupy the top percentile of an otherwise low-detail image.
    threshold = max(float(np.percentile(sm, 90)), 0.02)
    strong = sm >= threshold
    dot = sx * dx + sy * dy
    denom = sm * dm + 1e-8
    orientation = np.abs(dot / denom)
    agreement = float(np.mean(orientation[strong])) if np.any(strong) else 1.0
    output_threshold = max(float(np.percentile(dm, 95)), 0.02)
    new_edge = (dm >= output_threshold) & (sm <= 0.005) & (dm > sm * 3.0 + 0.01)
    return {
        "strong_edge_orientation_agreement": round(agreement, 6),
        "new_strong_edge_fraction": round(float(np.mean(new_edge)), 6),
    }


def difference_metrics(source: np.ndarray, output: np.ndarray) -> dict[str, float]:
    absolute = np.abs(output.astype(np.float32) - source.astype(np.float32))
    pixel_delta = np.mean(absolute, axis=2)
    source_luma = np.sum(source * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=2)
    output_luma = np.sum(output * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=2)
    return {
        "mean_absolute_rgb_delta": round(float(np.mean(absolute)), 6),
        "p95_pixel_rgb_delta": round(float(np.percentile(pixel_delta, 95)), 6),
        "mean_absolute_luma_delta": round(float(np.mean(np.abs(output_luma - source_luma))), 6),
        "changed_pixel_fraction_2_255": round(float(np.mean(pixel_delta >= (2.0 / 255.0))), 6),
    }


def strategy_warnings(recipe: dict, difference: dict[str, float]) -> list[str]:
    intensity = recipe.get("strategy", {}).get("intensity")
    mean_delta = difference["mean_absolute_rgb_delta"]
    p95_delta = difference["p95_pixel_rgb_delta"]
    warnings = []
    if intensity == "standard" and mean_delta < 0.015 and p95_delta < 0.04:
        warnings.append("standard strategy produced a low visual delta; review intent or strengthen the grade")
    elif intensity == "bold" and (mean_delta < 0.03 or p95_delta < 0.07):
        warnings.append("bold strategy did not produce a clearly strong visual delta; strengthen or explain the limit")
    elif intensity == "conservative" and mean_delta > 0.10:
        warnings.append("conservative strategy produced a large visual delta; review the grade")
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Check preservation and clipping after a grade.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output_image", type=Path)
    parser.add_argument("--recipe", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    recipe = load_recipe(args.recipe)
    source, source_alpha, _ = load_image(args.input)
    result, result_alpha, _ = load_image(args.output_image)
    hard_failures = []
    if source.shape != result.shape:
        hard_failures.append("image dimensions or channel topology changed")
    if (source_alpha is None) != (result_alpha is None):
        hard_failures.append("alpha structure changed")

    source_analysis = analyze_array(source)
    result_analysis = analyze_array(result)
    warnings = []
    source_clip = source_analysis["clipping"]["any_channel_high_fraction"]
    result_clip = result_analysis["clipping"]["any_channel_high_fraction"]
    if result_clip > source_clip + 0.005:
        warnings.append("high-channel clipping increased by more than 0.5 percentage points")
    source_black = source_analysis["clipping"]["near_black_fraction"]
    result_black = result_analysis["clipping"]["near_black_fraction"]
    if result_black > source_black + 0.02:
        warnings.append("near-black pixels increased by more than 2 percentage points; review shadow detail")
    if result_analysis["saturation"]["extreme_fraction"] > source_analysis["saturation"]["extreme_fraction"] + 0.01:
        warnings.append("extreme saturation increased by more than 1 percentage point")
    if recipe["output"].get("format", "png") == "jpeg":
        warnings.append("JPEG output is a lossy derivative")
    skin_enabled = recipe.get("protection", {}).get("skin", {}).get("enabled", False)
    if skin_enabled and source_analysis["skin_candidate_fraction"] < 0.001:
        warnings.append("skin protection was enabled but no reliable skin candidate was detected")
    if skin_enabled and source_analysis["skin_candidate_fraction"] > 0.35:
        warnings.append("skin candidate mask covers more than 35 percent; visually review for false positives")

    structure = gradient_metrics(source, result) if source.shape == result.shape else {}
    difference = difference_metrics(source, result) if source.shape == result.shape else {}
    if difference:
        warnings.extend(strategy_warnings(recipe, difference))
    if structure and structure["strong_edge_orientation_agreement"] < 0.98:
        warnings.append("strong-edge orientation agreement fell below 0.98")
    if structure and structure["new_strong_edge_fraction"] > 0.01:
        warnings.append("new strong edges exceed 1 percent of pixels")

    report = {
        "schema_version": "1.0",
        "status": "fail" if hard_failures else ("warn" if warnings else "pass"),
        "hard_failures": hard_failures,
        "warnings": warnings,
        "structure": structure,
        "difference": difference,
        "source": source_analysis,
        "output": result_analysis,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(args.output)
    return 1 if hard_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
