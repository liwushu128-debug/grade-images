# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "grade-images"
sys.path.insert(0, str(ROOT / "tools"))

from package_skill import FIXED_TIMESTAMP, build_archive  # noqa: E402


class RepositoryTests(unittest.TestCase):
    def test_skill_frontmatter_and_folder_name_agree(self) -> None:
        content = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\n"))
        frontmatter = content.split("---", 2)[1]
        fields = {}
        for line in frontmatter.strip().splitlines():
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
        self.assertEqual(set(fields), {"name", "description"})
        self.assertEqual(fields["name"], SKILL.name)
        self.assertTrue(fields["description"])

    def test_repository_docs_do_not_leak_into_skill_package(self) -> None:
        forbidden = {"README.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md"}
        packaged_names = {path.name for path in SKILL.rglob("*") if path.is_file()}
        self.assertTrue(forbidden.isdisjoint(packaged_names))

    def test_release_archive_is_deterministic_and_clean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.zip"
            second = Path(directory) / "second.zip"
            first_digest = build_archive(first)
            second_digest = build_archive(second)
            self.assertEqual(first_digest, second_digest)
            self.assertEqual(first_digest, hashlib.sha256(first.read_bytes()).hexdigest())
            with zipfile.ZipFile(first) as archive:
                names = archive.namelist()
                self.assertIn("grade-images/SKILL.md", names)
                self.assertIn("grade-images/requirements-raw.txt", names)
                self.assertIn("grade-images/references/raw-processing.md", names)
                self.assertIn("grade-images/references/film-color-catalog.json", names)
                self.assertIn("grade-images/scripts/route_film.py", names)
                self.assertIn("grade-images/assets/recipes/classic-negative-standard.json", names)
                self.assertIn("grade-images/references/classic-documentary-catalog.json", names)
                self.assertIn("grade-images/references/classic-documentary.md", names)
                self.assertIn("grade-images/scripts/route_documentary.py", names)
                self.assertIn("grade-images/assets/recipes/documentary-vivid-standard.json", names)
                self.assertIn("grade-images/assets/recipes/documentary-archive-standard.json", names)
                self.assertIn("grade-images/assets/recipes/documentary-earth-standard.json", names)
                self.assertIn("grade-images/references/texture-refinement.md", names)
                self.assertIn("grade-images/assets/recipes/output-refine-standard.json", names)
                self.assertIn("grade-images/assets/recipes/documentary-vivid-refine.json", names)
                self.assertTrue(all(name.startswith("grade-images/") for name in names))
                self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))
                self.assertTrue(all(info.date_time == FIXED_TIMESTAMP for info in archive.infolist()))


if __name__ == "__main__":
    unittest.main()
