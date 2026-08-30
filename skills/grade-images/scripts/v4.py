# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from correct import run_correction
from grade_core import analyze_array, load_image, load_recipe, render_array, save_image, sha256_file
from scene import build_intent_record, scene_evidence
from variants import build_contact_sheet


GRAPH_ORDER = (
    "decode",
    "color_manage",
    "correction",
    "look",
    "protection",
    "effects",
    "texture",
    "gamut",
    "encode",
)


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_intent_ir(prompt: str, measurements: dict[str, Any], evidence: dict[str, Any], people_evidence: str) -> dict[str, Any]:
    record = build_intent_record(prompt, measurements, evidence, people_evidence)
    return {
        "schema_version": "2.0",
        "kind": "grade-images.intent-ir",
        "intent": record["intent"],
        "source_facts": record["source_facts"],
        "constraints": {
            "preservation": "strict",
            "geometry_changes": False,
            "generative_changes": False,
            "effect_permission": record["intent"]["effects"]["permission"],
            "texture_permission": record["intent"]["texture"]["permission"],
            "correction_round_budget": 2,
        },
        "routing": record["routing"],
        "provenance": {
            "prompt": prompt,
            "people_evidence": people_evidence,
            "field_sources_recorded": True,
        },
    }


def build_evidence_graph(measurements: dict[str, Any], evidence: dict[str, Any], intent_ir: dict[str, Any]) -> dict[str, Any]:
    skin = evidence["skin_color_candidate"]
    nodes = [
        {"id": "source.tonality", "kind": "measurement", "value": measurements["luminance_percentiles_linear"]},
        {"id": "source.saturation", "kind": "measurement", "value": measurements["saturation"]},
        {"id": "scene.skin-color", "kind": "spatial-evidence", "value": skin},
        {"id": "intent.effects", "kind": "permission", "value": intent_ir["constraints"]["effect_permission"]},
        {"id": "intent.texture", "kind": "permission", "value": intent_ir["constraints"]["texture_permission"]},
        {"id": "route.skin-protection", "kind": "decision", "value": intent_ir["routing"]["skin_protection"]},
    ]
    edges = [
        {"from": "scene.skin-color", "to": "route.skin-protection", "relation": "supports"},
        {"from": "intent.effects", "to": "route.skin-protection", "relation": "independent"},
        {"from": "intent.texture", "to": "route.skin-protection", "relation": "independent"},
    ]
    graph = {"schema_version": "2.0", "kind": "grade-images.evidence-graph", "nodes": nodes, "edges": edges}
    graph["graph_sha256"] = _canonical_hash(graph)
    return graph


def compile_render_graph(input_path: Path, recipe: dict[str, Any], intent_ir: dict[str, Any]) -> dict[str, Any]:
    compiled_recipe = copy.deepcopy(recipe)
    skin_decision = intent_ir["routing"]["skin_protection"]["decision"]
    if skin_decision == "disable":
        compiled_recipe.setdefault("protection", {}).setdefault("skin", {})["enabled"] = False
    elif skin_decision == "review":
        raise ValueError("intent IR requires skin-protection review before graph compilation")
    nodes = [
        {"id": name, "order": index, "active": True, "params": {}}
        for index, name in enumerate(GRAPH_ORDER)
    ]
    params = {node["id"]: node["params"] for node in nodes}
    params["decode"].update({"input": str(input_path.resolve()), "input_sha256": sha256_file(input_path)})
    params["color_manage"].update({"working_profile": "sRGB", "linear_light": True})
    params["correction"].update(compiled_recipe.get("correction", {}))
    params["look"].update(compiled_recipe.get("look", {}))
    params["protection"].update(compiled_recipe.get("protection", {}))
    params["effects"].update(compiled_recipe.get("effects", {}))
    params["texture"].update(compiled_recipe.get("texture", {}))
    params["gamut"].update({"method": "luminance-preserving-chroma-compression"})
    params["encode"].update(compiled_recipe.get("output", {}))
    for node in nodes:
        if node["id"] in {"effects", "texture"} and not node["params"]:
            node["active"] = False
    graph = {
        "schema_version": "2.0",
        "kind": "grade-images.render-graph",
        "backend": "legacy-fused-v1",
        "compatibility": {"recipe_schema": recipe["schema_version"], "legacy_pixel_math": True},
        "nodes": nodes,
        "compiled_recipe": compiled_recipe,
        "deterministic": True,
    }
    graph["graph_sha256"] = _canonical_hash(graph)
    return graph


def execute_render_graph(source, graph: dict[str, Any]):
    if tuple(node["id"] for node in graph["nodes"]) != GRAPH_ORDER:
        raise ValueError("render graph node order is invalid")
    if graph.get("backend") != "legacy-fused-v1":
        raise ValueError("unsupported render graph backend")
    return render_array(source, graph["compiled_recipe"])


def run_v4(
    input_path: Path,
    prompt: str,
    recipe_path: Path,
    output_dir: Path,
    *,
    people_evidence: str = "unknown",
    max_size: int = 1200,
    auto_correct: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source, alpha, metadata = load_image(input_path, max_size=max_size)
    measurements = analyze_array(source)
    evidence = scene_evidence(source)
    intent_ir = build_intent_ir(prompt, measurements, evidence, people_evidence)
    evidence_graph = build_evidence_graph(measurements, evidence, intent_ir)
    recipe = load_recipe(recipe_path)
    render_graph = compile_render_graph(input_path, recipe, intent_ir)
    legacy_result, _ = render_array(source, recipe)
    graph_result, graph_diagnostics = execute_render_graph(source, render_graph)

    intent_path = output_dir / "intent-ir.json"
    evidence_path = output_dir / "evidence-graph.json"
    graph_path = output_dir / "render-graph.json"
    route_path = output_dir / "scene-route.json"
    intent_path.write_text(json.dumps(intent_ir, indent=2, ensure_ascii=False), encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence_graph, indent=2, ensure_ascii=False), encoding="utf-8")
    graph_path.write_text(json.dumps(render_graph, indent=2, ensure_ascii=False), encoding="utf-8")
    route_record = {
        "schema_version": "1.0",
        "input_sha256": sha256_file(input_path),
        "routing": intent_ir["routing"],
    }
    route_path.write_text(json.dumps(route_record, indent=2), encoding="utf-8")

    final_result = graph_result
    correction_manifest = None
    if auto_correct:
        correction = run_correction(
            input_path,
            recipe_path,
            output_dir / "controller",
            max_size=max_size,
            route_path=route_path,
        )
        correction_manifest = correction
        corrected_recipe = load_recipe(Path(correction["recipe"]))
        render_graph = compile_render_graph(input_path, corrected_recipe, intent_ir)
        graph_path.write_text(json.dumps(render_graph, indent=2, ensure_ascii=False), encoding="utf-8")
        final_result, graph_diagnostics = execute_render_graph(source, render_graph)

    output_recipe = copy.deepcopy(render_graph["compiled_recipe"])
    output_recipe["output"]["format"] = "png"
    final_path = output_dir / f"{input_path.stem}--v4.png"
    save_image(final_path, final_result, alpha, output_recipe, metadata, png_compress_level=2)
    comparison_path = output_dir / f"{input_path.stem}--v4-comparison.png"
    build_contact_sheet(
        [("Original", source), ("Legacy v0.3.x", legacy_result), ("v0.4.0", final_result)],
        comparison_path,
        columns=2,
        png_compress_level=1,
    )
    manifest = {
        "schema_version": "2.0",
        "status": "pass" if not correction_manifest or correction_manifest["status"] == "pass" else "needs-review",
        "input": str(input_path.resolve()),
        "input_sha256": sha256_file(input_path),
        "intent_ir": str(intent_path.resolve()),
        "evidence_graph": str(evidence_path.resolve()),
        "render_graph": str(graph_path.resolve()),
        "render_graph_sha256": render_graph["graph_sha256"],
        "legacy_backend": "legacy-fused-v1",
        "graph_diagnostics": graph_diagnostics,
        "correction_manifest": correction_manifest,
        "output": str(final_path.resolve()),
        "comparison_sheet": str(comparison_path.resolve()),
    }
    manifest_path = output_dir / "v4-manifest.json"
    manifest["manifest"] = str(manifest_path.resolve())
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile and run the grade-images v0.4.0 pipeline.")
    parser.add_argument("input", type=Path)
    parser.add_argument("prompt")
    parser.add_argument("--recipe", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--people-evidence", choices=("present", "absent", "unknown"), default="unknown")
    parser.add_argument("--max-size", type=int, default=1200)
    parser.add_argument("--no-auto-correct", action="store_true")
    args = parser.parse_args()
    manifest = run_v4(
        args.input,
        args.prompt,
        args.recipe,
        args.output_dir,
        people_evidence=args.people_evidence,
        max_size=args.max_size,
        auto_correct=not args.no_auto_correct,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
