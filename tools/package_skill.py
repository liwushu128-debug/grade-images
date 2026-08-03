# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import hashlib
import os
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "grade-images"
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _included_files() -> list[Path]:
    if not (SKILL / "SKILL.md").is_file():
        raise RuntimeError(f"missing skill entrypoint: {SKILL / 'SKILL.md'}")
    files = []
    for path in SKILL.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(SKILL)
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(SKILL).as_posix())


def build_archive(output: Path) -> str:
    output = output.resolve()
    try:
        output.relative_to(SKILL.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("release archive must not be written inside the skill folder")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    # Store without compression so bytes remain reproducible across zlib
    # versions and operating systems. The complete skill is intentionally small.
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
        for source in _included_files():
            relative = Path("grade-images") / source.relative_to(SKILL)
            info = zipfile.ZipInfo(relative.as_posix(), date_time=FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_STORED)
    os.replace(temporary, output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic grade-images skill archive.")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "grade-images.zip")
    args = parser.parse_args()
    digest = build_archive(args.output)
    print(args.output.resolve())
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
