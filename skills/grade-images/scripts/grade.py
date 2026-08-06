# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from grade_core import (
    RecipeError,
    load_image,
    load_recipe,
    render_array,
    save_image,
    sha256_file,
)


def validate_command(recipe_path: Path) -> int:
    load_recipe(recipe_path)
    print(f"valid: {recipe_path}")
    return 0


def render_command(input_path: Path, recipe_path: Path, output_path: Path, max_size: int | None) -> int:
    total_started = time.perf_counter()
    if input_path.resolve() == output_path.resolve():
        raise RecipeError("output must not overwrite the input")
    hash_started = time.perf_counter()
    source_hash_before = sha256_file(input_path)
    input_hash_seconds = time.perf_counter() - hash_started
    recipe = load_recipe(recipe_path)
    load_started = time.perf_counter()
    rgb, alpha, metadata = load_image(input_path, max_size=max_size)
    load_seconds = time.perf_counter() - load_started
    render_started = time.perf_counter()
    result, diagnostics = render_array(rgb, recipe)
    render_seconds = time.perf_counter() - render_started
    is_raw = metadata.get("raw_development") is not None
    png_compress_level = 2 if is_raw and output_path.suffix.lower() == ".png" else 6
    save_started = time.perf_counter()
    save_image(
        output_path,
        result,
        alpha,
        recipe,
        metadata,
        png_compress_level=png_compress_level,
    )
    save_seconds = time.perf_counter() - save_started
    source_hash_after = sha256_file(input_path)
    if source_hash_before != source_hash_after:
        output_path.unlink(missing_ok=True)
        raise RuntimeError("source file changed during rendering")

    recipe_copy = output_path.with_suffix(output_path.suffix + ".recipe.json")
    shutil.copyfile(recipe_path, recipe_copy)
    output_hash_started = time.perf_counter()
    output_hash = sha256_file(output_path)
    output_hash_seconds = time.perf_counter() - output_hash_started
    manifest = {
        "schema_version": "1.0",
        "input": str(input_path.resolve()),
        "input_sha256": source_hash_before,
        "output": str(output_path.resolve()),
        "output_sha256": output_hash,
        "preview": max_size is not None,
        "source_width": metadata["source_size"][0],
        "source_height": metadata["source_size"][1],
        "output_width": int(result.shape[1]),
        "output_height": int(result.shape[0]),
        "has_alpha": alpha is not None,
        "color_management": metadata["color_management"],
        "raw_development": metadata.get("raw_development"),
        "output_encoding": {
            "format": output_path.suffix.lower().lstrip("."),
            "png_compress_level": png_compress_level if output_path.suffix.lower() == ".png" else None,
            "lossless": output_path.suffix.lower() == ".png",
        },
        "warnings": metadata["warnings"],
        "diagnostics": diagnostics,
        "timing_seconds": {
            "input_hash": round(input_hash_seconds, 4),
            "load_and_raw_develop": round(load_seconds, 4),
            "grade": round(render_seconds, 4),
            "save": round(save_seconds, 4),
            "output_hash": round(output_hash_seconds, 4),
            "total_before_manifest": round(time.perf_counter() - total_started, 4),
        },
    }
    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(output_path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and render strict photo color-grade recipes.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("recipe", type=Path)
    render_parser = subparsers.add_parser("render")
    render_parser.add_argument("input", type=Path)
    render_parser.add_argument("--recipe", required=True, type=Path)
    render_parser.add_argument("--output", required=True, type=Path)
    render_parser.add_argument("--max-size", type=int)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            return validate_command(args.recipe)
        return render_command(args.input, args.recipe, args.output, args.max_size)
    except (RecipeError, OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
