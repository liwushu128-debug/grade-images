# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from grade_core import load_image, load_recipe, luminance, srgb_to_linear, validate_recipe


def _geometric_normalize(values: np.ndarray) -> np.ndarray:
    safe = np.clip(values.astype(np.float64), 1e-6, None)
    return safe / float(np.prod(safe) ** (1.0 / len(safe)))


def bounded_geometric_normalize(values: np.ndarray, low: float, high: float) -> np.ndarray:
    """Project positive gains into bounds while retaining geometric mean 1."""
    logs = np.log(np.clip(values.astype(np.float64), 1e-9, None))
    lower_log, upper_log = math.log(low), math.log(high)
    left, right = -10.0, 10.0
    for _ in range(64):
        shift = (left + right) / 2.0
        total = float(np.sum(np.clip(logs + shift, lower_log, upper_log)))
        if total < 0.0:
            left = shift
        else:
            right = shift
    return np.exp(np.clip(logs + (left + right) / 2.0, lower_log, upper_log))


def _percentile_zone_color(encoded_rgb: np.ndarray, linear_luma: np.ndarray, low: float, high: float) -> np.ndarray:
    low_value, high_value = np.percentile(linear_luma, [low, high])
    mask = (linear_luma >= low_value) & (linear_luma <= high_value)
    if not np.any(mask):
        return np.array([0.5, 0.5, 0.5], dtype=np.float64)
    return np.median(encoded_rgb[mask], axis=0).astype(np.float64)


def image_match_stats(encoded_rgb: np.ndarray) -> dict[str, Any]:
    linear = srgb_to_linear(encoded_rgb)
    luma = luminance(linear)
    low, median, high = [float(value) for value in np.percentile(luma, [5, 50, 95])]
    valid = (luma >= low) & (luma <= high)
    channel_mean = np.mean(linear[valid], axis=0) if np.any(valid) else np.mean(linear, axis=(0, 1))
    maximum = np.max(encoded_rgb, axis=2)
    minimum = np.min(encoded_rgb, axis=2)
    saturation = np.zeros_like(maximum)
    np.divide(maximum - minimum, maximum, out=saturation, where=maximum > 1e-6)
    return {
        "luma": {"p05": low, "p50": median, "p95": high, "range": max(high - low, 1e-6)},
        "balance": _geometric_normalize(channel_mean),
        "saturation_median": float(np.median(saturation)),
        "saturation_p95": float(np.percentile(saturation, 95)),
        "shadow_color": _percentile_zone_color(encoded_rgb, luma, 8, 32),
        "highlight_color": _percentile_zone_color(encoded_rgb, luma, 68, 92),
    }


def _delta_color(source: np.ndarray, reference: np.ndarray) -> tuple[list[float], float]:
    source_chroma = source - float(np.mean(source))
    reference_chroma = reference - float(np.mean(reference))
    delta = reference_chroma - source_chroma
    norm = float(np.linalg.norm(delta))
    if norm < 1e-6:
        return [0.5, 0.5, 0.5], 0.0
    direction = delta / norm
    return [round(float(value), 6) for value in np.clip(0.5 + direction * 0.18, 0.0, 1.0)], norm


def derive_match_recipe(
    source_rgb: np.ndarray,
    reference_rgb: np.ndarray,
    template: dict[str, Any],
    strength: float = 0.65,
    skin_protection: bool | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not 0.0 <= strength <= 1.0:
        raise ValueError("strength must be in [0, 1]")
    source = image_match_stats(source_rgb)
    reference = image_match_stats(reference_rgb)
    recipe = copy.deepcopy(template)
    intensity = "conservative" if strength < 0.5 else ("bold" if strength >= 0.8 else "standard")
    recipe["strategy"] = {
        "intensity": intensity,
        "style": "reference",
        "selection": "inferred",
    }
    if skin_protection is not None:
        recipe.setdefault("protection", {}).setdefault("skin", {})["enabled"] = skin_protection

    exposure = math.log2(max(reference["luma"]["p50"], 1e-6) / max(source["luma"]["p50"], 1e-6))
    # Make match strength a real safety envelope: a 0.4 match may alter
    # exposure by at most 0.4 EV. This prevents a dark reference with unrelated
    # lighting geometry from turning a normal scene into a low-light scene.
    exposure = float(np.clip(exposure * strength, -strength, strength))
    gains = (reference["balance"] / source["balance"]) ** strength
    gains = bounded_geometric_normalize(gains, 0.8, 1.25)

    contrast_ratio = reference["luma"]["range"] / source["luma"]["range"]
    curve_strength = float(np.clip(math.log2(max(contrast_ratio, 1e-6)) * 0.35 * strength, -0.6, 0.6))
    median_ratio = reference["saturation_median"] / max(source["saturation_median"], 0.05)
    p95_ratio = reference["saturation_p95"] / max(source["saturation_p95"], 0.05)
    # Use the more conservative distribution target. Matching only the median
    # can drive already-colorful regions into clipping.
    saturation_ratio = min(median_ratio, p95_ratio)
    saturation = float(np.clip(1.0 + (saturation_ratio - 1.0) * strength, 0.65, 1.35))
    use_vibrance = abs(median_ratio - p95_ratio) >= 0.15
    vibrance = 0.0
    if use_vibrance:
        desired_median_factor = 1.0 + (median_ratio - 1.0) * strength
        vibrance = float(
            np.clip(
                (desired_median_factor - 1.0) / max(1.0 - source["saturation_median"], 0.1),
                -1.0,
                2.0,
            )
        )

    shadow_color, shadow_delta = _delta_color(source["shadow_color"], reference["shadow_color"])
    highlight_color, highlight_delta = _delta_color(source["highlight_color"], reference["highlight_color"])
    split_strength = float(np.clip(max(shadow_delta, highlight_delta) * 0.28 * strength, 0.0, 0.07))
    if shadow_delta < 0.01:
        shadow_color = [0.5, 0.5, 0.5]
    if highlight_delta < 0.01:
        highlight_color = [0.5, 0.5, 0.5]

    correction = recipe.setdefault("correction", {})
    correction["exposure_ev"] = round(float(correction.get("exposure_ev", 0.0)) + exposure, 6)
    correction.setdefault("white_balance", {})["rgb_gains"] = [round(float(value), 6) for value in gains]
    look = recipe.setdefault("look", {})
    look.setdefault("tone_curve", {})["strength"] = round(curve_strength, 6)
    look.setdefault("cdl", {})["saturation"] = 1.0
    if use_vibrance and abs(vibrance) >= 0.05:
        recipe["schema_version"] = "1.1"
        look["saturation"] = 1.0
        look["vibrance"] = round(vibrance, 6)
        chroma_control = "vibrance"
    else:
        look.pop("vibrance", None)
        look["saturation"] = round(saturation, 6)
        chroma_control = "saturation"
    look["split_tone"] = {
        "shadows": shadow_color,
        "highlights": highlight_color,
        "balance": 0.0,
        "strength": round(split_strength, 6),
    }
    recipe["intent"] = (
        f"Reference-derived color match at strength {strength:.2f}; "
        "matches tonal distribution and color tendencies without neural style transfer"
    )
    validate_recipe(recipe)
    diagnostics = {
        "strength": strength,
        "strategy_intensity": intensity,
        "exposure_delta_ev": exposure,
        "exposure_limit_ev": strength,
        "white_balance_rgb_gains": [float(value) for value in gains],
        "contrast_ratio": contrast_ratio,
        "tone_curve_strength": curve_strength,
        "saturation_ratio": saturation_ratio,
        "saturation_median_ratio": median_ratio,
        "saturation_p95_ratio": p95_ratio,
        "output_saturation": saturation,
        "chroma_control": chroma_control,
        "output_vibrance": vibrance if chroma_control == "vibrance" else 0.0,
        "shadow_chroma_delta": shadow_delta,
        "highlight_chroma_delta": highlight_delta,
        "split_tone_strength": split_strength,
        "skin_protection_enabled": recipe.get("protection", {}).get("skin", {}).get("enabled", False),
    }
    return recipe, diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive a strict color-grade recipe from a reference image.")
    parser.add_argument("source", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--strength", type=float, default=0.65)
    parser.add_argument("--disable-skin-protection", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source, _, _ = load_image(args.source, max_size=1600)
    reference, _, _ = load_image(args.reference, max_size=1600)
    skin_override = False if args.disable_skin_protection else None
    recipe, diagnostics = derive_match_recipe(
        source, reference, load_recipe(args.template), args.strength, skin_protection=skin_override
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(recipe, indent=2), encoding="utf-8")
    diagnostics_path = args.output.with_suffix(args.output.suffix + ".match.json")
    diagnostics_path.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
