# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from grade_core import RAW_EXTENSIONS, analyze_array, load_image, sha256_file


def _array_sha256(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def run_raw_checks(
    inputs: list[Path],
    output_path: Path,
    *,
    max_size: int = 1200,
    full_decode: bool = False,
    require_camera_wb: bool = False,
) -> dict[str, Any]:
    if not inputs:
        raise ValueError("at least one RAW input is required")
    if max_size < 64:
        raise ValueError("max_size must be at least 64")
    cases = []
    for path in inputs:
        started = time.perf_counter()
        case: dict[str, Any] = {
            "path": str(path.resolve()),
            "status": "fail",
            "error": None,
        }
        try:
            if path.suffix.lower() not in RAW_EXTENSIONS:
                raise ValueError(f"not a recognized camera RAW suffix: {path.suffix or '<none>'}")
            source_hash = sha256_file(path)
            first_started = time.perf_counter()
            first, alpha, metadata = load_image(path, max_size=max_size)
            first_elapsed = time.perf_counter() - first_started
            second_started = time.perf_counter()
            second, _, second_metadata = load_image(path, max_size=max_size)
            second_elapsed = time.perf_counter() - second_started
            if alpha is not None:
                raise RuntimeError("camera RAW unexpectedly decoded with alpha")
            if metadata.get("raw_development") is None:
                raise RuntimeError("RAW development provenance is missing")
            white_balance_source = metadata["raw_development"].get("white_balance_source")
            if require_camera_wb and white_balance_source != "camera":
                raise RuntimeError(
                    "camera white balance was required but the decoder used "
                    f"{white_balance_source or 'an unknown source'}"
                )
            if not np.array_equal(first, second):
                raise RuntimeError("repeated RAW preview decoding was not deterministic")
            if metadata["raw_development"] != second_metadata.get("raw_development"):
                raise RuntimeError("repeated RAW development metadata changed")
            case.update({
                "status": "pass",
                "source_sha256": source_hash,
                "source_unchanged": sha256_file(path) == source_hash,
                "preview_width": int(first.shape[1]),
                "preview_height": int(first.shape[0]),
                "preview_rgb_sha256": _array_sha256(first),
                "deterministic_preview": True,
                "raw_development": metadata["raw_development"],
                "warnings": metadata["warnings"],
                "measurements": analyze_array(first),
                "timing_seconds": {
                    "first_preview_decode": round(first_elapsed, 4),
                    "second_preview_decode": round(second_elapsed, 4),
                },
            })
            if full_decode:
                full_started = time.perf_counter()
                full, full_alpha, full_metadata = load_image(path)
                if full_alpha is not None:
                    raise RuntimeError("full RAW decode unexpectedly returned alpha")
                case["full_decode"] = {
                    "width": int(full.shape[1]),
                    "height": int(full.shape[0]),
                    "rgb_sha256": _array_sha256(full),
                    "decoder_output_bps": full_metadata["raw_development"]["output_bps"],
                    "timing_seconds": round(time.perf_counter() - full_started, 4),
                }
            if not case["source_unchanged"]:
                raise RuntimeError("RAW source file changed during validation")
        except (OSError, ValueError, RuntimeError) as error:
            case["status"] = "fail"
            case["error"] = str(error)
        case["total_seconds"] = round(time.perf_counter() - started, 4)
        cases.append(case)
    report = {
        "schema_version": "1.0",
        "status": "fail" if any(case["status"] == "fail" for case in cases) else "pass",
        "max_size": max_size,
        "full_decode_requested": full_decode,
        "require_camera_wb": require_camera_wb,
        "cases": cases,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report"] = str(output_path.resolve())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify deterministic camera RAW decoding, provenance, and source preservation."
    )
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-size", type=int, default=1200)
    parser.add_argument("--full-decode", action="store_true")
    parser.add_argument(
        "--require-camera-wb",
        action="store_true",
        help="fail when a file must fall back from valid camera white balance",
    )
    args = parser.parse_args()
    report = run_raw_checks(
        args.inputs,
        args.output,
        max_size=args.max_size,
        full_decode=args.full_decode,
        require_camera_wb=args.require_camera_wb,
    )
    print(report["report"])
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
