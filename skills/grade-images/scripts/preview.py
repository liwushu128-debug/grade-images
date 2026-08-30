# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import shutil
import time
from pathlib import Path

from compare import (
    difference_metrics,
    gradient_metrics,
    reference_adjustment_suggestions,
    reference_match_metrics,
    strategy_warnings,
    texture_metrics,
    texture_warnings,
)
from grade_core import (
    RecipeError,
    analyze_array,
    load_image,
    load_recipe,
    render_array,
    save_image,
    sha256_file,
)
from variants import build_contact_sheet


REFERENCE_REQUIREMENTS = {
    "conservative": 0.20,
    "standard": 0.40,
    "bold": 0.60,
    "transformative": 0.75,
}


def _quality_report(
    source,
    result,
    recipe: dict,
    reference=None,
) -> dict:
    # Every metric reads immutable arrays and returns a standalone value. Keep
    # the same math while avoiding serial passes over the same preview pixels.
    with ThreadPoolExecutor(max_workers=6) as executor:
        source_future = executor.submit(analyze_array, source)
        result_future = executor.submit(analyze_array, result)
        reference_future = (
            executor.submit(analyze_array, reference) if reference is not None else None
        )
        difference_future = executor.submit(difference_metrics, source, result)
        structure_future = executor.submit(gradient_metrics, source, result)
        texture_enabled = recipe.get("texture", {}).get("output_sharpen", {}).get("enabled", False)
        texture_future = executor.submit(texture_metrics, source, result) if texture_enabled else None
        source_analysis = source_future.result()
        result_analysis = result_future.result()
        reference_analysis = reference_future.result() if reference_future else None
        difference = difference_future.result()
        structure = structure_future.result()
        texture = texture_future.result() if texture_future else {
            "mean_gradient_ratio": 1.0,
            "p90_gradient_ratio": 1.0,
            "highpass_std_ratio": 1.0,
            "not_evaluated": "texture processing disabled",
        }
    warnings = strategy_warnings(recipe, difference)
    recommendations = []

    allowed_clip = max(
        source_analysis["clipping"]["any_channel_high_fraction"],
        reference_analysis["clipping"]["any_channel_high_fraction"]
        if reference_analysis else 0.0,
    )
    if result_analysis["clipping"]["any_channel_high_fraction"] > allowed_clip + 0.005:
        warnings.append("high-channel clipping increased by more than 0.5 percentage points")
    intentional_black = float(
        recipe.get("quality_tolerances", {}).get("intentional_near_black_increase", 0.0)
    )
    allowed_black = max(
        source_analysis["clipping"]["near_black_fraction"] + intentional_black,
        reference_analysis["clipping"]["near_black_fraction"] if reference_analysis else 0.0,
    )
    if result_analysis["clipping"]["near_black_fraction"] > allowed_black + 0.02:
        warnings.append("near-black pixels increased by more than 2 percentage points; review shadow detail")
    allowed_extreme = max(
        source_analysis["saturation"]["extreme_fraction"],
        reference_analysis["saturation"]["extreme_fraction"] if reference_analysis else 0.0,
    )
    if result_analysis["saturation"]["extreme_fraction"] > allowed_extreme + 0.01:
        warnings.append("extreme saturation increased by more than 1 percentage point")
    if structure["strong_edge_orientation_agreement"] < 0.98:
        warnings.append("strong-edge orientation agreement fell below 0.98")
    glow_enabled = recipe.get("effects", {}).get("source_glow", {}).get("enabled", False)
    new_edge_limit = 0.04 if glow_enabled else 0.01
    if structure["new_strong_edge_fraction"] > new_edge_limit:
        warnings.append(
            f"new strong-edge or glow-boundary gradients exceed {new_edge_limit:.0%} of pixels"
        )
    warnings.extend(texture_warnings(recipe, texture))

    target_match = {}
    if reference_analysis:
        target_match = reference_match_metrics(source_analysis, result_analysis, reference_analysis)
        required = REFERENCE_REQUIREMENTS.get(
            recipe.get("strategy", {}).get("intensity"), 0.40
        )
        target_match["required_improvement_fraction"] = required
        target_match["passed"] = target_match["improvement_fraction"] >= required
        if not target_match["passed"]:
            warnings.append(
                f"reference distribution match did not reach the {required:.0%} improvement required for this intensity"
            )
            recommendations = reference_adjustment_suggestions(result_analysis, reference_analysis)

    return {
        "schema_version": "1.0",
        "status": "warn" if warnings else "pass",
        "warnings": warnings,
        "recommendations": recommendations,
        "structure": structure,
        "texture": texture,
        "difference": difference,
        "target_match": target_match,
        "source": source_analysis,
        "output": result_analysis,
        "reference": reference_analysis,
    }


def render_preview(
    input_path: Path,
    recipe_path: Path,
    output_dir: Path,
    max_size: int = 1200,
    reference_path: Path | None = None,
    label: str | None = None,
) -> dict:
    if max_size < 64:
        raise ValueError("max_size must be at least 64")
    started = time.perf_counter()
    source_hash = sha256_file(input_path)
    recipe = load_recipe(recipe_path)
    source, alpha, metadata = load_image(input_path, max_size=max_size)
    load_elapsed = time.perf_counter() - started
    render_started = time.perf_counter()
    result, diagnostics = render_array(source, recipe)
    render_elapsed = time.perf_counter() - render_started
    reference = None
    if reference_path:
        reference, _, _ = load_image(reference_path, max_size=max_size)

    output_dir.mkdir(parents=True, exist_ok=True)
    extension = ".jpg" if recipe["output"].get("format") == "jpeg" else ".png"
    preview_path = output_dir / f"{input_path.stem}--preview{extension}"
    recipe_copy = output_dir / f"{input_path.stem}--preview.recipe.json"
    report_path = output_dir / f"{input_path.stem}--preview.report.json"
    sheet_path = output_dir / f"{input_path.stem}--preview.comparison.png"
    if preview_path.resolve() == input_path.resolve():
        raise RecipeError("preview output must not overwrite the input")

    strategy = recipe.get("strategy", {})
    display_label = label or " · ".join(
        part.title() for part in (
            strategy.get("intensity", "Preview"),
            strategy.get("style", "Custom"),
        )
    )
    panels = [("Original", source), (display_label, result)]
    if reference is not None:
        panels.append(("Reference", reference))

    artifact_started = time.perf_counter()
    stage_seconds: dict[str, float] = {}

    def save_preview() -> None:
        stage_started = time.perf_counter()
        save_image(preview_path, result, alpha, recipe, metadata, png_compress_level=2)
        stage_seconds["preview_encode"] = time.perf_counter() - stage_started

    def analyze_quality() -> dict:
        stage_started = time.perf_counter()
        value = _quality_report(source, result, recipe, reference=reference)
        stage_seconds["quality_analysis"] = time.perf_counter() - stage_started
        return value

    def save_sheet() -> None:
        stage_started = time.perf_counter()
        build_contact_sheet(panels, sheet_path, columns=2, png_compress_level=1)
        stage_seconds["comparison_sheet"] = time.perf_counter() - stage_started

    # These jobs read immutable arrays and write distinct files. Parallelizing
    # them changes latency only; rendered pixels and quality math stay stable.
    with ThreadPoolExecutor(max_workers=3) as executor:
        preview_future = executor.submit(save_preview)
        report_future = executor.submit(analyze_quality)
        sheet_future = executor.submit(save_sheet)
        preview_future.result()
        report = report_future.result()
        sheet_future.result()

    write_started = time.perf_counter()
    shutil.copyfile(recipe_path, recipe_copy)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    stage_seconds["artifact_writes"] = time.perf_counter() - write_started
    artifact_elapsed = time.perf_counter() - artifact_started
    if sha256_file(input_path) != source_hash:
        raise RuntimeError("source file changed during preview rendering")

    manifest = {
        "schema_version": "1.0",
        "input": str(input_path.resolve()),
        "input_sha256": source_hash,
        "recipe": str(recipe_copy.resolve()),
        "preview": str(preview_path.resolve()),
        "comparison_sheet": str(sheet_path.resolve()),
        "quality_report": str(report_path.resolve()),
        "quality_status": report["status"],
        "max_size": max_size,
        "source_size": list(metadata["source_size"]),
        "color_management": metadata["color_management"],
        "raw_development": metadata.get("raw_development"),
        "source_warnings": metadata["warnings"],
        "render_diagnostics": diagnostics,
        "timing_seconds": {
            "load": round(load_elapsed, 4),
            "render": round(render_elapsed, 4),
            "preview_encode": round(stage_seconds["preview_encode"], 4),
            "quality_analysis": round(stage_seconds["quality_analysis"], 4),
            "comparison_sheet": round(stage_seconds["comparison_sheet"], 4),
            "artifact_writes": round(stage_seconds["artifact_writes"], 4),
            "parallel_artifacts_wall": round(artifact_elapsed, 4),
            "total": round(time.perf_counter() - started, 4),
        },
    }
    manifest_path = output_dir / f"{input_path.stem}--preview.manifest.json"
    manifest["manifest"] = str(manifest_path.resolve())
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render, compare, label, and report one deterministic preview in a single pass."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--recipe", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-size", type=int, default=1200)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--label")
    args = parser.parse_args()
    try:
        manifest = render_preview(
            args.input,
            args.recipe,
            args.output_dir,
            max_size=args.max_size,
            reference_path=args.reference,
            label=args.label,
        )
    except (RecipeError, OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
