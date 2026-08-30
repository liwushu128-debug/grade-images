# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import PIL

from grade_core import RecipeError, sha256_file
from preview import render_preview


def _percentile(values: list[float], percentile: float) -> float:
    return round(float(np.percentile(np.asarray(values, dtype=np.float64), percentile)), 4)


def run_benchmark(
    input_path: Path,
    recipe_path: Path,
    output_dir: Path,
    *,
    runs: int = 7,
    warmup: int = 1,
    max_size: int = 1200,
) -> dict:
    if runs < 3:
        raise ValueError("runs must be at least 3")
    if warmup < 0:
        raise ValueError("warmup must not be negative")
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for index in range(warmup + runs):
        run_dir = output_dir / (f"warmup-{index + 1}" if index < warmup else f"run-{index - warmup + 1}")
        manifest = render_preview(input_path, recipe_path, run_dir, max_size=max_size)
        if index >= warmup:
            records.append(manifest["timing_seconds"])

    totals = [float(record["total"]) for record in records]
    report = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": str(input_path.resolve()),
        "input_sha256": sha256_file(input_path),
        "recipe": str(recipe_path.resolve()),
        "recipe_sha256": sha256_file(recipe_path),
        "max_size": max_size,
        "warmup_runs": warmup,
        "measured_runs": runs,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pillow": PIL.__version__,
            "numpy": np.__version__,
        },
        "summary_seconds": {
            "p50_total": round(statistics.median(totals), 4),
            "p95_total": _percentile(totals, 95),
            "min_total": round(min(totals), 4),
            "max_total": round(max(totals), 4),
        },
        "runs": records,
    }
    report_path = output_dir / "benchmark.json"
    report["report"] = str(report_path.resolve())
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the end-to-end deterministic preview path.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--recipe", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--max-size", type=int, default=1200)
    args = parser.parse_args()
    try:
        report = run_benchmark(
            args.input,
            args.recipe,
            args.output_dir,
            runs=args.runs,
            warmup=args.warmup,
            max_size=args.max_size,
        )
    except (RecipeError, OSError, RuntimeError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
