# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import numpy as np

from grade_core import (
    RecipeError,
    load_image,
    load_recipe,
    render_array,
    save_image,
    sha256_file,
    validate_recipe,
)
from preview import _quality_report
from variants import build_contact_sheet


CAUSE_RULES = {
    "near-black pixels increased": "shadow_crush",
    "low visual delta": "intent_underpowered",
    "did not produce a clearly strong visual delta": "intent_underpowered",
    "extreme saturation increased": "chroma_clipping",
    "high-channel clipping increased": "highlight_clipping",
    "strong-edge orientation agreement": "structure_change",
    "new strong-edge": "structure_change",
}


def classify_warnings(report: dict[str, Any]) -> list[str]:
    causes = []
    for warning in report.get("warnings", []):
        cause = next((value for text, value in CAUSE_RULES.items() if text in warning), "unmapped")
        if cause not in causes:
            causes.append(cause)
    return causes


def _scaled(value: float, center: float, factor: float, low: float, high: float) -> float:
    return float(np.clip(center + (value - center) * factor, low, high))


def _creative_color_scale(recipe: dict[str, Any], factor: float, saturation: float | None = None) -> None:
    look = recipe.get("look", {})
    cdl = look.get("cdl", {})
    for key, center, low, high in (
        ("slope", 1.0, 0.25, 4.0),
        ("offset", 0.0, -0.25, 0.25),
        ("power", 1.0, 0.25, 4.0),
    ):
        if key in cdl:
            cdl[key] = [_scaled(value, center, factor, low, high) for value in cdl[key]]
    if "saturation" in look:
        look["saturation"] = (
            float(np.clip(saturation, 0.0, 2.0))
            if saturation is not None
            else _scaled(look["saturation"], 1.0, factor, 0.0, 2.0)
        )
    if "vibrance" in look:
        look["vibrance"] = _scaled(look["vibrance"], 0.0, factor, -1.0, 2.0)
    split = look.get("split_tone", {})
    if "strength" in split:
        split["strength"] = _scaled(split["strength"], 0.0, factor, 0.0, 0.25)


def bounded_candidates(
    recipe: dict[str, Any],
    causes: list[str],
    *,
    source_near_black: float | None = None,
    source_extreme_saturation: float | None = None,
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    if "unmapped" in causes or any(cause in causes for cause in ("structure_change", "highlight_clipping")):
        return []
    # A source can be visibly low-key before the generic 20% warning threshold;
    # use the safer low-light bracket once the source has a substantial dark field.
    adaptive = source_near_black is not None and source_extreme_saturation is not None
    low_light = source_near_black is not None and source_near_black > 0.12
    chroma_sensitive = (
        source_extreme_saturation is not None and source_extreme_saturation > 0.05
    )
    shadow_values = [None]
    if "shadow_crush" in causes:
        if not adaptive:
            shadow_values = [0.0, 0.05, 0.10, 0.15]
        elif low_light:
            shadow_values = [-0.4, -0.5]
        elif "intent_underpowered" in causes:
            shadow_values = [0.0, -0.2] if chroma_sensitive else [-0.5, -0.6, -0.7]
        else:
            shadow_values = [0.0, 0.05, 0.10, 0.15]
    color_factors = [1.0]
    if "intent_underpowered" in causes:
        color_factors = [6.0, 7.0, 8.0] if low_light else [4.0, 6.0, 7.0, 8.0]
    saturation_values: list[float | None] = [None]
    if adaptive and "intent_underpowered" in causes and "saturation" in recipe.get("look", {}):
        if low_light:
            saturation_values = [0.75, 0.65, 0.55]
        elif chroma_sensitive:
            saturation_values = [0.65, 0.55, 0.45]
            color_factors = [4.0, 6.0]
        elif "shadow_crush" in causes:
            saturation_values = [0.75, 0.65, 0.55, 0.45]
            color_factors = [4.0, 8.0]
    candidates = []
    for tone in shadow_values:
        for factor in color_factors:
            for saturation in saturation_values:
                candidate = copy.deepcopy(recipe)
                adjustment: dict[str, Any] = {"creative_color_factor": factor}
                if tone is not None:
                    candidate.setdefault("correction", {})["black_point"] = 0.0
                    candidate.setdefault("look", {}).setdefault("tone_curve", {})["strength"] = tone
                    adjustment.update({"black_point": 0.0, "tone_curve_strength": tone})
                if saturation is not None:
                    adjustment["global_saturation"] = saturation
                _creative_color_scale(candidate, factor, saturation)
                candidate["intent"] = (
                    f"{recipe.get('intent', 'Creative grade')}; bounded correction for "
                    f"{', '.join(causes)} with {adjustment}"
                )
                validate_recipe(candidate)
                label = f"tone-{tone if tone is not None else 'keep'}--color-{factor:g}x"
                if saturation is not None:
                    label += f"--sat-{saturation:g}"
                candidates.append((label, candidate, adjustment))
    return candidates


def _score(report: dict[str, Any], adjustment: dict[str, Any]) -> tuple[Any, ...]:
    causes = classify_warnings(report)
    safety = sum(cause not in {"intent_underpowered"} for cause in causes)
    intent = sum(cause == "intent_underpowered" for cause in causes)
    return (
        safety,
        intent,
        len(report.get("warnings", [])),
        float(adjustment.get("creative_color_factor", 1.0)),
        float(adjustment.get("tone_curve_strength", 0.0)),
    )


def run_correction(
    input_path: Path,
    recipe_path: Path,
    output_dir: Path,
    *,
    max_size: int = 1200,
    max_rounds: int = 2,
    route_path: Path | None = None,
) -> dict[str, Any]:
    if max_rounds != 2:
        raise ValueError("v0.3.7 correction budget is exactly two rounds")
    source_hash = sha256_file(input_path)
    source, alpha, metadata = load_image(input_path, max_size=max_size)
    initial_recipe = load_recipe(recipe_path)
    route = None
    if route_path is not None:
        route = json.loads(route_path.read_text(encoding="utf-8"))
        if route.get("input_sha256") != source_hash:
            raise ValueError("route input hash does not match the correction input")
        skin_route = route.get("routing", {}).get("skin_protection", {})
        decision = skin_route.get("decision")
        if decision == "disable":
            initial_recipe.setdefault("protection", {}).setdefault("skin", {})["enabled"] = False
        elif decision == "review":
            raise ValueError("skin-protection route requires review before correction")
    initial_result, initial_diagnostics = render_array(source, initial_recipe)
    initial_report = _quality_report(source, initial_result, initial_recipe)
    causes = classify_warnings(initial_report)
    output_dir.mkdir(parents=True, exist_ok=True)

    records = [{
        "round": 1,
        "label": "initial",
        "causes": causes,
        "warnings": initial_report["warnings"],
        "difference": initial_report["difference"],
        "clipping": initial_report["output"]["clipping"],
        "structure": initial_report["structure"],
    }]
    selected_recipe = initial_recipe
    selected_result = initial_result
    selected_report = initial_report
    selected_diagnostics = initial_diagnostics
    selected_label = "initial"
    evaluated = []

    if initial_report["warnings"]:
        source_near_black = initial_report["source"]["clipping"]["near_black_fraction"]
        source_extreme_saturation = initial_report["source"]["saturation"]["extreme_fraction"]
        for label, candidate, adjustment in bounded_candidates(
            initial_recipe,
            causes,
            source_near_black=source_near_black,
            source_extreme_saturation=source_extreme_saturation,
        ):
            result, diagnostics = render_array(source, candidate)
            report = _quality_report(source, result, candidate)
            evaluated.append((label, candidate, adjustment, result, diagnostics, report))
        if evaluated:
            selected = min(evaluated, key=lambda item: _score(item[5], item[2]))
            selected_label, selected_recipe, adjustment, selected_result, selected_diagnostics, selected_report = selected
            records.append({
                "round": 2,
                "label": selected_label,
                "adjustment": adjustment,
                "causes": classify_warnings(selected_report),
                "warnings": selected_report["warnings"],
                "difference": selected_report["difference"],
                "clipping": selected_report["output"]["clipping"],
                "structure": selected_report["structure"],
            })

    status = "pass" if not selected_report["warnings"] else "needs-review"
    stop_reason = "quality gates passed" if status == "pass" else (
        "no mapped safe adjustment" if not evaluated else "two-round correction budget exhausted"
    )
    final_path = output_dir / f"{input_path.stem}--corrected.png"
    recipe_out = output_dir / f"{input_path.stem}--corrected.recipe.json"
    report_out = output_dir / f"{input_path.stem}--corrected.report.json"
    sheet_out = output_dir / f"{input_path.stem}--correction.comparison.png"
    output_recipe = copy.deepcopy(selected_recipe)
    output_recipe["output"]["format"] = "png"
    save_image(final_path, selected_result, alpha, output_recipe, metadata, png_compress_level=2)
    recipe_out.write_text(json.dumps(output_recipe, indent=2), encoding="utf-8")
    report_out.write_text(json.dumps(selected_report, indent=2), encoding="utf-8")
    build_contact_sheet(
        [("Original", source), ("Initial", initial_result), (f"Round 2 · {selected_label}", selected_result)],
        sheet_out,
        columns=2,
        png_compress_level=1,
    )
    if sha256_file(input_path) != source_hash:
        raise RuntimeError("source file changed during bounded correction")
    manifest = {
        "schema_version": "1.0",
        "status": status,
        "stop_reason": stop_reason,
        "input": str(input_path.resolve()),
        "input_sha256": source_hash,
        "initial_recipe": str(recipe_path.resolve()),
        "route": str(route_path.resolve()) if route_path else None,
        "selected_label": selected_label,
        "candidate_count": len(evaluated),
        "rounds": records,
        "output": str(final_path.resolve()),
        "recipe": str(recipe_out.resolve()),
        "quality_report": str(report_out.resolve()),
        "comparison_sheet": str(sheet_out.resolve()),
        "diagnostics": selected_diagnostics,
    }
    manifest_path = output_dir / f"{input_path.stem}--correction.manifest.json"
    manifest["manifest"] = str(manifest_path.resolve())
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a two-round bounded correction search.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--recipe", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-size", type=int, default=1200)
    parser.add_argument("--route", type=Path)
    args = parser.parse_args()
    try:
        manifest = run_correction(
            args.input,
            args.recipe,
            args.output_dir,
            max_size=args.max_size,
            route_path=args.route,
        )
    except (RecipeError, OSError, RuntimeError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
