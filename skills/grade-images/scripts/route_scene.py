# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import json
from pathlib import Path

from grade_core import analyze_array, load_image, sha256_file
from scene import build_intent_record, scene_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an auditable intent and scene-routing record.")
    parser.add_argument("input", type=Path)
    parser.add_argument("prompt")
    parser.add_argument("--people-evidence", choices=("present", "absent", "unknown"), default="unknown")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-size", type=int, default=1200)
    args = parser.parse_args()
    rgb, _, metadata = load_image(args.input, max_size=args.max_size)
    measurements = analyze_array(rgb)
    record = build_intent_record(
        args.prompt,
        measurements,
        scene_evidence(rgb),
        args.people_evidence,
    )
    record["input"] = str(args.input.resolve())
    record["input_sha256"] = sha256_file(args.input)
    record["source_size"] = list(metadata["source_size"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
