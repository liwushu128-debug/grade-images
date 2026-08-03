# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageCms


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "grade-images"
sys.path.insert(0, str(SKILL / "scripts"))

import batch as batch_script  # noqa: E402
import analyze as analyze_script  # noqa: E402
from batch import derive_batch_recipes  # noqa: E402
from compare import difference_metrics, gradient_metrics, strategy_warnings  # noqa: E402
from grade_core import RecipeError, load_image, load_recipe, render_array, save_image, validate_recipe  # noqa: E402
from match import derive_match_recipe  # noqa: E402


class GradeCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.neutral_path = SKILL / "assets" / "recipes" / "neutral-correction.json"
        cls.cinematic_path = SKILL / "assets" / "recipes" / "muted-cinematic.json"
        cls.low_light_path = SKILL / "assets" / "recipes" / "low-light-cinematic.json"
        cls.natural_path = SKILL / "assets" / "recipes" / "natural-standard.json"
        cls.bold_path = SKILL / "assets" / "recipes" / "bold-cinematic.json"

    def test_bundled_recipes_validate(self) -> None:
        load_recipe(self.neutral_path)
        load_recipe(self.cinematic_path)
        load_recipe(self.low_light_path)
        load_recipe(self.natural_path)
        load_recipe(self.bold_path)

    def test_double_saturation_adjustment_fails_closed(self) -> None:
        recipe = copy.deepcopy(load_recipe(self.neutral_path))
        recipe["look"]["cdl"]["saturation"] = 0.96
        recipe["look"]["saturation"] = 0.96
        with self.assertRaisesRegex(RecipeError, "only one saturation control"):
            validate_recipe(recipe)

    def test_strategy_metadata_is_validated(self) -> None:
        recipe = copy.deepcopy(load_recipe(self.neutral_path))
        recipe["strategy"]["intensity"] = "extreme"
        with self.assertRaisesRegex(RecipeError, "strategy.intensity"):
            validate_recipe(recipe)

    def test_forbidden_operation_fails_closed(self) -> None:
        recipe = load_recipe(self.neutral_path)
        recipe = copy.deepcopy(recipe)
        recipe["look"]["sharpen"] = 20
        with self.assertRaises(RecipeError):
            validate_recipe(recipe)

    def test_neutral_round_trip_preserves_decoded_pixels(self) -> None:
        recipe = load_recipe(self.neutral_path)
        source = np.linspace(0.0, 1.0, 64 * 64 * 3, dtype=np.float32).reshape(64, 64, 3)
        result, _ = render_array(source, recipe)
        source8 = np.uint8(np.round(source * 255.0))
        result8 = np.uint8(np.round(result * 255.0))
        self.assertLessEqual(int(np.max(np.abs(source8.astype(int) - result8.astype(int)))), 1)

    def test_render_is_deterministic(self) -> None:
        recipe = load_recipe(self.cinematic_path)
        rng = np.random.default_rng(42)
        source = rng.random((80, 96, 3), dtype=np.float32)
        first, first_diag = render_array(source, recipe)
        second, second_diag = render_array(source, recipe)
        self.assertTrue(np.array_equal(first, second))
        self.assertEqual(first_diag, second_diag)

    def test_skin_protection_reduces_creative_change(self) -> None:
        recipe = load_recipe(self.cinematic_path)
        without = copy.deepcopy(recipe)
        without["protection"]["skin"]["enabled"] = False
        source = np.zeros((120, 160, 3), dtype=np.float32)
        source[:, :80] = np.array([0.72, 0.48, 0.36], dtype=np.float32)
        source[:, 80:] = np.array([0.18, 0.38, 0.72], dtype=np.float32)
        protected, diagnostics = render_array(source, recipe)
        unprotected, _ = render_array(source, without)
        skin_delta_protected = float(np.mean(np.abs(protected[:, :80] - source[:, :80])))
        skin_delta_unprotected = float(np.mean(np.abs(unprotected[:, :80] - source[:, :80])))
        self.assertGreater(diagnostics["skin_fraction"], 0.1)
        self.assertLess(skin_delta_protected, skin_delta_unprotected)

    def test_png_save_preserves_dimensions_and_alpha(self) -> None:
        recipe = load_recipe(self.neutral_path)
        source = np.full((24, 32, 3), 0.4, dtype=np.float32)
        alpha = np.linspace(0.0, 1.0, 24 * 32, dtype=np.float32).reshape(24, 32, 1)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.png"
            save_image(output, source, alpha, recipe, {"icc_profile": None, "exif": None})
            with Image.open(output) as image:
                self.assertEqual(image.size, (32, 24))
                self.assertEqual(image.mode, "RGBA")

    def test_output_format_must_match_suffix(self) -> None:
        recipe = load_recipe(self.neutral_path)
        source = np.full((4, 4, 3), 0.5, dtype=np.float32)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RecipeError):
                save_image(Path(directory) / "result.jpg", source, None, recipe, {})

    def test_reference_match_derives_bounded_warm_bright_correction(self) -> None:
        template = load_recipe(self.neutral_path)
        source = np.full((48, 64, 3), [0.28, 0.34, 0.44], dtype=np.float32)
        reference = np.full((48, 64, 3), [0.68, 0.58, 0.46], dtype=np.float32)
        recipe, diagnostics = derive_match_recipe(source, reference, template, strength=0.65)
        validate_recipe(recipe)
        gains = recipe["correction"]["white_balance"]["rgb_gains"]
        self.assertGreater(recipe["correction"]["exposure_ev"], 0.0)
        self.assertGreater(gains[0], gains[2])
        self.assertLessEqual(abs(diagnostics["exposure_delta_ev"]), 0.65)
        self.assertEqual(recipe["preservation"]["mode"], "strict")
        self.assertEqual(recipe["strategy"]["intensity"], "standard")
        self.assertEqual(recipe["strategy"]["style"], "reference")

        no_skin, no_skin_diagnostics = derive_match_recipe(
            source, reference, template, strength=0.65, skin_protection=False
        )
        self.assertFalse(no_skin["protection"]["skin"]["enabled"])
        self.assertFalse(no_skin_diagnostics["skin_protection_enabled"])

    def test_batch_uses_individual_corrections_and_identical_shared_look(self) -> None:
        template = load_recipe(self.cinematic_path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = []
            for name, color in (
                ("dark-cool.png", [45, 65, 105]),
                ("middle.png", [115, 110, 100]),
                ("bright-warm.png", [215, 170, 120]),
            ):
                path = root / name
                Image.new("RGB", (32, 24), tuple(color)).save(path)
                inputs.append(path)
            recipes, manifest = derive_batch_recipes(inputs, template, strength=0.8)
        exposures = [recipe["correction"]["exposure_ev"] for _, recipe in recipes]
        looks = [recipe["look"] for _, recipe in recipes]
        self.assertEqual(len(set(exposures)), 3)
        self.assertTrue(all(look == template["look"] for look in looks))
        self.assertEqual(len(manifest["images"]), 3)
        for _, recipe in recipes:
            validate_recipe(recipe)

    def test_batch_cli_avoids_recipe_name_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_dir = root / "a"
            second_dir = root / "b"
            output_dir = root / "recipes"
            first_dir.mkdir()
            second_dir.mkdir()
            first = first_dir / "photo.png"
            second = second_dir / "photo.png"
            Image.new("RGB", (16, 16), (80, 90, 100)).save(first)
            Image.new("RGB", (16, 16), (140, 130, 120)).save(second)
            argv = [
                "batch.py", str(first), str(second), "--look", str(self.neutral_path),
                "--output-dir", str(output_dir), "--disable-skin-protection",
            ]
            with patch.object(sys, "argv", argv):
                self.assertEqual(batch_script.main(), 0)
            generated = list(output_dir.glob("photo-*.grade.json"))
            manifest = json.loads((output_dir / "batch-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(generated), 2)
            self.assertEqual(len({item["recipe"] for item in manifest["images"]}), 2)
            self.assertFalse(manifest["skin_protection_enabled"])
            for recipe_path in generated:
                self.assertFalse(json.loads(recipe_path.read_text())["protection"]["skin"]["enabled"])

    def test_embedded_profile_is_converted_and_output_is_tagged_srgb(self) -> None:
        recipe = load_recipe(self.neutral_path)
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "profiled.png"
            output = root / "result.png"
            Image.new("RGB", (20, 12), (90, 120, 150)).save(source, icc_profile=profile)
            rgb, alpha, metadata = load_image(source)
            self.assertEqual(metadata["color_management"], "converted_embedded_icc_to_srgb")
            save_image(output, rgb, alpha, recipe, metadata)
            with Image.open(output) as image:
                self.assertTrue(image.info.get("icc_profile"))

    def test_structure_metric_ignores_color_grade_but_detects_new_edges(self) -> None:
        y, x = np.mgrid[0:120, 0:160]
        source = np.stack(
            [0.15 + 0.6 * x / 159.0, 0.2 + 0.5 * y / 119.0, np.full_like(x, 0.4)],
            axis=2,
        ).astype(np.float32)
        source[40:80, 55:105] *= 0.45
        graded = np.clip(source * np.array([1.18, 1.0, 0.82], dtype=np.float32) + 0.03, 0.0, 1.0)
        safe = gradient_metrics(source, graded)
        self.assertGreater(safe["strong_edge_orientation_agreement"], 0.98)
        self.assertLess(safe["new_strong_edge_fraction"], 0.01)

        checker = graded.copy()
        pattern = ((x // 4 + y // 4) % 2).astype(bool)
        checker[pattern] = 1.0
        checker[~pattern] = 0.0
        damaged = gradient_metrics(source, checker)
        self.assertGreater(damaged["new_strong_edge_fraction"], 0.01)

    def test_difference_metrics_detect_underpowered_standard_and_bold_grades(self) -> None:
        source = np.full((32, 40, 3), [0.3, 0.45, 0.62], dtype=np.float32)
        tiny = np.clip(source + 0.002, 0.0, 1.0)
        difference = difference_metrics(source, tiny)
        standard = copy.deepcopy(load_recipe(self.natural_path))
        bold = copy.deepcopy(load_recipe(self.bold_path))
        self.assertTrue(any("standard strategy" in item for item in strategy_warnings(standard, difference)))
        self.assertTrue(any("bold strategy" in item for item in strategy_warnings(bold, difference)))

    def test_bold_template_has_more_visible_delta_than_conservative_template(self) -> None:
        y, x = np.mgrid[0:80, 0:96]
        source = np.stack(
            [0.18 + 0.62 * x / 95.0, 0.22 + 0.5 * y / 79.0, 0.3 + 0.32 * x / 95.0],
            axis=2,
        ).astype(np.float32)
        conservative, _ = render_array(source, load_recipe(self.cinematic_path))
        bold, _ = render_array(source, load_recipe(self.bold_path))
        conservative_delta = difference_metrics(source, conservative)["mean_absolute_rgb_delta"]
        bold_delta = difference_metrics(source, bold)["mean_absolute_rgb_delta"]
        self.assertGreater(bold_delta, conservative_delta * 1.5)

    def test_black_point_mapping_does_not_create_colored_channel_zeros(self) -> None:
        recipe = load_recipe(self.neutral_path)
        recipe = copy.deepcopy(recipe)
        recipe["correction"]["black_point"] = 0.08
        recipe["correction"]["white_balance"]["rgb_gains"] = [0.85, 1.0, 1.18]
        source = np.full((20, 20, 3), [0.24, 0.18, 0.12], dtype=np.float32)
        output, _ = render_array(source, recipe)
        channel_is_zero = output[0, 0] <= 1.0 / 255.0
        self.assertIn(int(np.sum(channel_is_zero)), {0, 3})

    def test_unsupported_format_and_high_bit_depth_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bitmap = root / "input.bmp"
            high_depth = root / "input16.png"
            Image.new("RGB", (8, 8), (20, 40, 60)).save(bitmap)
            Image.fromarray(np.full((8, 8), 32000, dtype=np.uint16)).save(high_depth)
            with self.assertRaises(RecipeError):
                load_image(bitmap)
            with self.assertRaises(RecipeError):
                load_image(high_depth)

    def test_untagged_cmyk_jpeg_reports_uncertain_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "cmyk.jpg"
            Image.new("CMYK", (12, 10), (10, 20, 30, 5)).save(source)
            rgb, alpha, metadata = load_image(source)
            self.assertEqual(rgb.shape, (10, 12, 3))
            self.assertIsNone(alpha)
            self.assertEqual(metadata["color_management"], "untagged_cmyk_converted_to_rgb")
            self.assertTrue(metadata["warnings"])

    def test_analyze_cli_reports_current_color_management_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.png"
            report = root / "analysis.json"
            Image.new("RGB", (14, 9), (30, 60, 90)).save(source)
            with patch.object(sys, "argv", ["analyze.py", str(source), "--output", str(report)]):
                self.assertEqual(analyze_script.main(), 0)
            image_report = json.loads(report.read_text(encoding="utf-8"))["images"][0]
            self.assertFalse(image_report["has_icc_profile"])
            self.assertEqual(image_report["working_profile"], "sRGB")
            self.assertEqual(image_report["color_management"], "assumed_srgb")


if __name__ == "__main__":
    unittest.main()
