# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from batch import derive_batch_recipes
from grade_core import analyze_array, load_image, load_recipe, render_array, save_image, sha256_file


def _pixel_hash(rgb: np.ndarray, alpha: np.ndarray | None) -> str:
    digest = hashlib.sha256()
    digest.update(np.uint8(np.round(np.clip(rgb, 0.0, 1.0) * 255.0)).tobytes())
    if alpha is not None:
        digest.update(np.uint8(np.round(np.clip(alpha, 0.0, 1.0) * 255.0)).tobytes())
    return digest.hexdigest()


def _robust_outliers(values: list[float], threshold: float = 3.5) -> list[bool]:
    array = np.asarray(values, dtype=np.float64)
    median = float(np.median(array))
    mad = float(np.median(np.abs(array - median)))
    if mad < 1e-8:
        return [abs(float(value) - median) > 1e-8 for value in array]
    scores = 0.6745 * np.abs(array - median) / mad
    return [bool(score > threshold) for score in scores]


def _look_hash(recipe: dict[str, Any]) -> str:
    payload = json.dumps(recipe.get("look", {}), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def render_batch(
    inputs: list[Path],
    look_path: Path,
    output_dir: Path,
    *,
    strength: float = 0.8,
    max_size: int = 1200,
    workers: int = 4,
    disable_skin_protection: bool = False,
) -> dict[str, Any]:
    if not inputs:
        raise ValueError("at least one input is required")
    if not 1 <= workers <= 8:
        raise ValueError("workers must be in [1, 8]")
    started = time.perf_counter()
    template = load_recipe(look_path)
    if disable_skin_protection:
        template.setdefault("protection", {}).setdefault("skin", {})["enabled"] = False
    recipes, recipe_manifest = derive_batch_recipes(inputs, template, strength)
    output_dir.mkdir(parents=True, exist_ok=True)
    look_hash = _look_hash(template)
    exposures = [float(item[1]["correction"]["exposure_ev"]) for item in recipes]
    gain_spreads = [
        float(max(item[1]["correction"]["white_balance"]["rgb_gains"]) / min(item[1]["correction"]["white_balance"]["rgb_gains"]))
        for item in recipes
    ]
    exposure_outliers = _robust_outliers(exposures)
    balance_outliers = _robust_outliers(gain_spreads)
    records: list[dict[str, Any] | None] = [None] * len(recipes)

    def render_one(index: int, input_path: Path, recipe: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        item_started = time.perf_counter()
        rgb, alpha, metadata = load_image(input_path, max_size=max_size)
        result, diagnostics = render_array(rgb, recipe)
        output_path = output_dir / f"{index + 1:04d}-{input_path.stem}.png"
        output_recipe = json.loads(json.dumps(recipe))
        output_recipe["output"]["format"] = "png"
        save_image(output_path, result, alpha, output_recipe, metadata, png_compress_level=2)
        analysis = analyze_array(result)
        array_bytes = int(rgb.nbytes + result.nbytes + (alpha.nbytes if alpha is not None else 0))
        return index, {
            "index": index,
            "input": str(input_path.resolve()),
            "input_sha256": sha256_file(input_path),
            "output": str(output_path.resolve()),
            "output_pixel_sha256": _pixel_hash(result, alpha),
            "recipe_look_sha256": _look_hash(recipe),
            "exposure_ev": float(recipe["correction"]["exposure_ev"]),
            "white_balance_rgb_gains": recipe["correction"]["white_balance"]["rgb_gains"],
            "output_luminance_median": analysis["luminance_percentiles_linear"]["50"],
            "output_saturation_median": analysis["saturation"]["median"],
            "array_working_bytes": array_bytes,
            "diagnostics": diagnostics,
            "elapsed_seconds": round(time.perf_counter() - item_started, 4),
        }

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(render_one, index, path, recipe): index
            for index, (path, recipe) in enumerate(recipes)
        }
        for future in as_completed(futures):
            index, record = future.result()
            records[index] = record

    completed = [record for record in records if record is not None]
    luma_values = [float(record["output_luminance_median"]) for record in completed]
    saturation_values = [float(record["output_saturation_median"]) for record in completed]
    luma_outliers = _robust_outliers(luma_values)
    saturation_outliers = _robust_outliers(saturation_values)
    for index, record in enumerate(completed):
        reasons = []
        if exposure_outliers[index]:
            reasons.append("correction_exposure")
        if balance_outliers[index]:
            reasons.append("correction_white_balance")
        if luma_outliers[index]:
            reasons.append("output_luminance")
        if saturation_outliers[index]:
            reasons.append("output_saturation")
        record["outlier_reasons"] = reasons
        record["is_outlier"] = bool(reasons)

    peak_item_bytes = max(record["array_working_bytes"] for record in completed)
    manifest = {
        "schema_version": "1.0",
        "input_count": len(inputs),
        "workers": workers,
        "max_size": max_size,
        "strength": strength,
        "shared_look_sha256": look_hash,
        "all_looks_identical": all(record["recipe_look_sha256"] == look_hash for record in completed),
        "output_order_deterministic": [record["index"] for record in completed] == list(range(len(completed))),
        "outlier_count": sum(record["is_outlier"] for record in completed),
        "estimated_peak_array_bytes": peak_item_bytes * min(workers, len(completed)),
        "timing_seconds": {"total": round(time.perf_counter() - started, 4)},
        "throughput_images_per_second": round(len(completed) / max(time.perf_counter() - started, 1e-9), 4),
        "recipe_normalization": recipe_manifest,
        "images": completed,
    }
    manifest_path = output_dir / "batch-render-manifest.json"
    manifest["manifest"] = str(manifest_path.resolve())
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a normalized batch with bounded parallelism and consistency evidence.")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--look", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--strength", type=float, default=0.8)
    parser.add_argument("--max-size", type=int, default=1200)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--disable-skin-protection", action="store_true")
    args = parser.parse_args()
    manifest = render_batch(
        args.inputs,
        args.look,
        args.output_dir,
        strength=args.strength,
        max_size=args.max_size,
        workers=args.workers,
        disable_skin_protection=args.disable_skin_protection,
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
