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
import compare as compare_script  # noqa: E402
import preview as preview_script  # noqa: E402
import variants as variants_script  # noqa: E402
from batch import derive_batch_recipes  # noqa: E402
from compare import (  # noqa: E402
    difference_metrics,
    gradient_metrics,
    reference_adjustment_suggestions,
    reference_match_metrics,
    strategy_warnings,
)
from grade_core import RecipeError, load_image, load_recipe, render_array, save_image, validate_recipe  # noqa: E402
from match import derive_match_recipe  # noqa: E402
from variants import derive_intensity_recipe, render_variants  # noqa: E402
from regress import run_regression  # noqa: E402
from search_match import STRENGTH_GRIDS, search_reference_match  # noqa: E402
from preview import render_preview  # noqa: E402


class GradeCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.neutral_path = SKILL / "assets" / "recipes" / "neutral-correction.json"
        cls.cinematic_path = SKILL / "assets" / "recipes" / "muted-cinematic.json"
        cls.low_light_path = SKILL / "assets" / "recipes" / "low-light-cinematic.json"
        cls.natural_path = SKILL / "assets" / "recipes" / "natural-standard.json"
        cls.bold_path = SKILL / "assets" / "recipes" / "bold-cinematic.json"
        cls.soft_glow_path = SKILL / "assets" / "recipes" / "soft-dream-source-glow.json"
        cls.transformative_path = SKILL / "assets" / "recipes" / "transformative-cool-violet.json"

    def test_bundled_recipes_validate(self) -> None:
        load_recipe(self.neutral_path)
        load_recipe(self.cinematic_path)
        load_recipe(self.low_light_path)
        load_recipe(self.natural_path)
        load_recipe(self.bold_path)
        load_recipe(self.soft_glow_path)
        load_recipe(self.transformative_path)

    def test_double_saturation_adjustment_fails_closed(self) -> None:
        recipe = copy.deepcopy(load_recipe(self.neutral_path))
        recipe["look"]["cdl"]["saturation"] = 0.96
        recipe["look"]["saturation"] = 0.96
        with self.assertRaisesRegex(RecipeError, "only one chroma control"):
            validate_recipe(recipe)

    def test_vibrance_requires_v11_and_cannot_stack_with_saturation(self) -> None:
        recipe = copy.deepcopy(load_recipe(self.neutral_path))
        recipe["look"]["vibrance"] = 1.2
        with self.assertRaisesRegex(RecipeError, "schema_version"):
            validate_recipe(recipe)
        recipe["schema_version"] = "1.1"
        validate_recipe(recipe)
        recipe["schema_version"] = "1.2"
        validate_recipe(recipe)
        recipe["look"]["saturation"] = 1.1
        with self.assertRaisesRegex(RecipeError, "only one chroma control"):
            validate_recipe(recipe)

    def test_positive_vibrance_boosts_muted_color_more_than_saturated_color(self) -> None:
        recipe = copy.deepcopy(load_recipe(self.neutral_path))
        recipe["schema_version"] = "1.1"
        recipe["look"]["vibrance"] = 1.5
        source = np.zeros((8, 16, 3), dtype=np.float32)
        source[:, :8] = [0.48, 0.42, 0.38]
        source[:, 8:] = [0.75, 0.18, 0.10]
        output, _ = render_array(source, recipe)
        muted_delta = float(np.mean(np.abs(output[:, :8] - source[:, :8])))
        saturated_delta = float(np.mean(np.abs(output[:, 8:] - source[:, 8:])))
        self.assertGreater(muted_delta, 0.0)
        self.assertGreater(muted_delta, saturated_delta * 0.25)
        self.assertLess(float(np.mean(output[:, 8:, 0] >= 254.0 / 255.0)), 0.1)

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

    def test_source_glow_requires_v11_and_explicit_user_consent(self) -> None:
        recipe = copy.deepcopy(load_recipe(self.neutral_path))
        recipe["effects"] = {
            "permission": "source-derived",
            "selection": "inferred",
            "source_glow": {
                "enabled": True,
                "threshold": 0.55,
                "knee": 0.12,
                "radius_fraction": 0.02,
                "strength": 0.12,
            },
        }
        with self.assertRaisesRegex(RecipeError, "schema_version"):
            validate_recipe(recipe)
        recipe["schema_version"] = "1.1"
        with self.assertRaisesRegex(RecipeError, "explicit user consent"):
            validate_recipe(recipe)
        recipe["effects"]["selection"] = "explicit-user"
        validate_recipe(recipe)

    def test_synthetic_light_effects_fail_closed(self) -> None:
        recipe = copy.deepcopy(load_recipe(self.neutral_path))
        recipe["schema_version"] = "1.1"
        recipe["effects"] = {
            "permission": "source-derived",
            "selection": "explicit-user",
            "lens_flare": {"enabled": True},
        }
        with self.assertRaisesRegex(RecipeError, "unknown or forbidden"):
            validate_recipe(recipe)

    def test_source_glow_is_deterministic_and_requires_source_highlights(self) -> None:
        recipe = copy.deepcopy(load_recipe(self.neutral_path))
        recipe["schema_version"] = "1.1"
        recipe["effects"] = {
            "permission": "source-derived",
            "selection": "explicit-user",
            "source_glow": {
                "enabled": True,
                "threshold": 0.55,
                "knee": 0.10,
                "radius_fraction": 0.025,
                "strength": 0.16,
            },
        }
        dark = np.full((64, 80, 3), 0.20, dtype=np.float32)
        dark_output, dark_diag = render_array(dark, recipe)
        self.assertLess(float(np.max(np.abs(dark_output - dark))), 1e-6)
        self.assertEqual(dark_diag["source_glow"]["source_highlight_fraction"], 0.0)

        source = dark.copy()
        source[24:40, 32:48] = 0.95
        first, first_diag = render_array(source, recipe)
        second, second_diag = render_array(source, recipe)
        self.assertTrue(np.array_equal(first, second))
        self.assertEqual(first_diag, second_diag)
        self.assertGreater(float(np.mean(first[20:44, 28:52] - source[20:44, 28:52])), 0.0)
        structure = gradient_metrics(source, first)
        self.assertGreater(structure["strong_edge_orientation_agreement"], 0.98)
        self.assertLess(structure["new_strong_edge_fraction"], 0.04)

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

    def test_reference_match_uses_vibrance_for_uneven_chroma_target(self) -> None:
        template = load_recipe(self.neutral_path)
        source = np.empty((40, 50, 3), dtype=np.float32)
        reference = np.empty_like(source)
        source[:, :40] = [0.50, 0.45, 0.40]
        source[:, 40:] = [0.80, 0.10, 0.10]
        reference[:, :40] = [0.70, 0.35, 0.20]
        reference[:, 40:] = [0.80, 0.10, 0.10]
        recipe, diagnostics = derive_match_recipe(source, reference, template, strength=0.90)
        validate_recipe(recipe)
        self.assertEqual(recipe["schema_version"], "1.1")
        self.assertEqual(diagnostics["chroma_control"], "vibrance")
        self.assertGreater(recipe["look"]["vibrance"], 0.0)
        self.assertEqual(recipe["look"]["saturation"], 1.0)

    def test_bidirectional_rich_soft_matching_moves_in_opposite_directions(self) -> None:
        y, x = np.mgrid[0:80, 0:120]
        x = x / 119.0
        y = y / 79.0
        rich = np.stack(
            [0.08 + 0.82 * x, 0.10 + 0.72 * y, 0.12 + 0.70 * (1.0 - x)], axis=2
        ).astype(np.float32)
        soft = np.clip(rich * 0.42 + 0.43, 0.0, 1.0).astype(np.float32)
        template = load_recipe(self.neutral_path)
        recipes = []
        improvements = []
        for source, reference in ((rich, soft), (soft, rich)):
            recipe, _ = derive_match_recipe(
                source, reference, template, strength=0.90, skin_protection=False
            )
            output, _ = render_array(source, recipe)
            metrics = reference_match_metrics(
                analyze_script.analyze_array(source),
                analyze_script.analyze_array(output),
                analyze_script.analyze_array(reference),
            )
            recipes.append(recipe)
            improvements.append(metrics["improvement_fraction"])
        self.assertGreater(improvements[0], 0.40)
        self.assertGreater(improvements[1], 0.40)
        self.assertGreater(recipes[0]["correction"]["exposure_ev"], 0.0)
        self.assertLess(recipes[1]["correction"]["exposure_ev"], 0.0)
        self.assertLess(recipes[0]["look"]["tone_curve"]["strength"], 0.0)
        self.assertGreater(recipes[1]["look"]["tone_curve"]["strength"], 0.0)

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

    def test_transformative_localized_change_does_not_require_large_global_mean(self) -> None:
        recipe = copy.deepcopy(load_recipe(self.transformative_path))
        localized = {
            "mean_absolute_rgb_delta": 0.025,
            "p95_pixel_rgb_delta": 0.12,
            "mean_absolute_luma_delta": 0.01,
            "changed_pixel_fraction_2_255": 0.18,
        }
        weak = dict(localized, p95_pixel_rgb_delta=0.05)
        self.assertFalse(strategy_warnings(recipe, localized))
        self.assertTrue(any("transformative strategy" in item for item in strategy_warnings(recipe, weak)))

    def test_reference_match_metrics_distinguish_safety_from_target_progress(self) -> None:
        source = analyze_script.analyze_array(np.full((20, 20, 3), [0.75, 0.72, 0.68], dtype=np.float32))
        output = analyze_script.analyze_array(np.full((20, 20, 3), [0.55, 0.48, 0.42], dtype=np.float32))
        reference = analyze_script.analyze_array(np.full((20, 20, 3), [0.35, 0.24, 0.18], dtype=np.float32))
        metrics = reference_match_metrics(source, output, reference)
        self.assertGreater(metrics["improvement_fraction"], 0.20)
        self.assertLess(metrics["output_distribution_distance"], metrics["source_distribution_distance"])

    def test_reference_metrics_report_zones_and_actionable_suggestions(self) -> None:
        output = analyze_script.analyze_array(
            np.full((20, 20, 3), [0.35, 0.37, 0.40], dtype=np.float32)
        )
        reference = analyze_script.analyze_array(
            np.full((20, 20, 3), [0.70, 0.50, 0.30], dtype=np.float32)
        )
        suggestions = reference_adjustment_suggestions(output, reference)
        dimensions = {item["dimension"] for item in suggestions}
        self.assertIn("exposure", dimensions)
        self.assertIn("color_balance", dimensions)
        self.assertIn("25", output["luminance_percentiles_linear"])
        self.assertIn("midtones", output["tonal_zone_mean_srgb"])

    def test_compare_cli_separates_preservation_from_reference_intent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            output = root / "output.png"
            reference = root / "reference.png"
            report = root / "report.json"
            recipe_path = root / "recipe.json"
            Image.new("RGB", (24, 18), (170, 165, 160)).save(source)
            Image.new("RGB", (24, 18), (170, 165, 160)).save(output)
            Image.new("RGB", (24, 18), (45, 35, 30)).save(reference)
            recipe = copy.deepcopy(load_recipe(self.neutral_path))
            recipe["protection"]["skin"] = {"enabled": False, "strength": 0.0}
            recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
            argv = [
                "compare.py",
                str(source),
                str(output),
                "--recipe",
                str(recipe_path),
                "--reference",
                str(reference),
                "--output",
                str(report),
            ]
            with patch.object(sys, "argv", argv):
                self.assertEqual(compare_script.main(), 0)
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result["preservation_status"], "pass")
            self.assertEqual(result["intent_match_status"], "warn")
            self.assertTrue(result["intent_warnings"])

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

    def test_variant_preview_keeps_outputs_and_builds_labeled_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            output_dir = root / "previews"
            y, x = np.mgrid[0:60, 0:80]
            rgb = np.stack(
                [40 + x * 2, 55 + y * 2, 90 + x], axis=2
            ).clip(0, 255).astype(np.uint8)
            Image.fromarray(rgb, mode="RGB").save(source)
            source_hash = variants_script.sha256_file(source)
            manifest = render_variants(
                source,
                [
                    ("Conservative", self.cinematic_path),
                    ("Standard", self.natural_path),
                    ("Bold", self.bold_path),
                ],
                output_dir,
                max_size=200,
                columns=2,
            )
            self.assertEqual(source_hash, variants_script.sha256_file(source))
            self.assertEqual(len(manifest["variants"]), 3)
            self.assertTrue(Path(manifest["comparison_sheet"]).is_file())
            self.assertTrue(Path(manifest["manifest"]).is_file())
            deltas = [item["difference"]["mean_absolute_rgb_delta"] for item in manifest["variants"]]
            self.assertGreater(max(deltas), min(deltas))
            for item in manifest["variants"]:
                self.assertTrue(Path(item["output"]).is_file())
                self.assertTrue(Path(item["recipe_copy"]).is_file())

    def test_single_pass_preview_keeps_artifacts_and_reports_timing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            reference = root / "reference.png"
            output_dir = root / "preview"
            y, x = np.mgrid[0:72, 0:108]
            warm = np.stack(
                [
                    0.18 + 0.62 * x / 107.0,
                    0.12 + 0.45 * y / 71.0,
                    np.full(x.shape, 0.16, dtype=np.float32),
                ],
                axis=2,
            ).clip(0.0, 1.0)
            cool = np.stack((warm[..., 2], warm[..., 1] * 0.9, warm[..., 0] * 0.8), axis=2)
            Image.fromarray(np.uint8(np.round(warm * 255.0)), mode="RGB").save(source)
            Image.fromarray(np.uint8(np.round(cool * 255.0)), mode="RGB").save(reference)
            source_hash = variants_script.sha256_file(source)
            manifest = render_preview(
                source,
                self.transformative_path,
                output_dir,
                max_size=160,
                reference_path=reference,
                label="Transformative test",
            )
            self.assertEqual(source_hash, variants_script.sha256_file(source))
            self.assertTrue(Path(manifest["preview"]).is_file())
            self.assertTrue(Path(manifest["comparison_sheet"]).is_file())
            self.assertTrue(Path(manifest["quality_report"]).is_file())
            self.assertTrue(Path(manifest["recipe"]).is_file())
            self.assertGreaterEqual(manifest["timing_seconds"]["total"], 0.0)
            report = json.loads(Path(manifest["quality_report"]).read_text(encoding="utf-8"))
            self.assertIn("difference", report)
            self.assertIn("target_match", report)

    def test_automatic_intensity_variants_scale_only_the_creative_look(self) -> None:
        base = load_recipe(self.bold_path)
        derived = {
            intensity: derive_intensity_recipe(base, intensity)
            for intensity in ("conservative", "standard", "bold")
        }
        for recipe in derived.values():
            validate_recipe(recipe)
            self.assertEqual(recipe["correction"], base["correction"])
            self.assertEqual(recipe.get("effects"), base.get("effects"))
            self.assertEqual(recipe["protection"], base["protection"])
        strengths = [
            derived[intensity]["look"]["tone_curve"]["strength"]
            for intensity in ("conservative", "standard", "bold")
        ]
        self.assertLess(strengths[0], strengths[1])
        self.assertLess(strengths[1], strengths[2])
        self.assertEqual(derived["bold"]["look"], base["look"])

    def test_transformative_derivation_scales_hue_change_without_broadening_selection(self) -> None:
        base = load_recipe(self.transformative_path)
        standard = derive_intensity_recipe(base, "standard")
        bold = derive_intensity_recipe(base, "bold")
        transformative = derive_intensity_recipe(base, "transformative")
        for recipe in (standard, bold, transformative):
            validate_recipe(recipe)
            self.assertEqual(recipe["correction"], base["correction"])
            self.assertEqual(recipe["protection"], base["protection"])
            self.assertEqual(
                recipe["look"]["hue_ranges"][0]["width_degrees"],
                base["look"]["hue_ranges"][0]["width_degrees"],
            )
            self.assertEqual(
                recipe["look"]["hue_ranges"][0]["feather_degrees"],
                base["look"]["hue_ranges"][0]["feather_degrees"],
            )
        shifts = [
            abs(recipe["look"]["hue_ranges"][0]["hue_shift_degrees"])
            for recipe in (standard, bold, transformative)
        ]
        self.assertLess(shifts[0], shifts[1])
        self.assertLess(shifts[1], shifts[2])
        self.assertEqual(
            standard["quality_tolerances"]["intentional_near_black_increase"], 0.0
        )
        self.assertEqual(bold["quality_tolerances"]["intentional_near_black_increase"], 0.0)
        self.assertGreater(
            transformative["quality_tolerances"]["intentional_near_black_increase"], 0.0
        )
        self.assertEqual(transformative["look"], base["look"])

    def test_local_regression_manifest_runs_without_committing_private_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "soft.png"
            reference = root / "rich.png"
            output_dir = root / "regression"
            y, x = np.mgrid[0:64, 0:96]
            soft = np.stack(
                [120 + x * 0.5, 130 + y * 0.4, 145 + x * 0.3], axis=2
            ).clip(0, 255).astype(np.uint8)
            rich = np.stack(
                [55 + x * 1.7, 70 + y * 1.2, 105 + x * 0.8], axis=2
            ).clip(0, 255).astype(np.uint8)
            Image.fromarray(soft, mode="RGB").save(source)
            Image.fromarray(rich, mode="RGB").save(reference)
            manifest_path = root / "cases.json"
            manifest_path.write_text(json.dumps({
                "schema_version": "1.0",
                "cases": [{
                    "name": "soft-to-rich",
                    "direction": "soft-to-rich",
                    "source": source.name,
                    "reference": reference.name,
                    "template": str(self.neutral_path),
                    "strength": 0.9,
                    "minimum_improvement_fraction": 0.0,
                    "skin_protection": False,
                }],
            }), encoding="utf-8")
            report = run_regression(manifest_path, output_dir)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["cases"][0]["direction"], "soft-to-rich")
            self.assertTrue(Path(report["cases"][0]["recipe"]).is_file())
            self.assertTrue(Path(report["report"]).is_file())

    def test_reference_search_stays_inside_selected_intensity_and_selects_best_safe_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "soft.png"
            reference = root / "rich.png"
            output_dir = root / "search"
            y, x = np.mgrid[0:72, 0:108]
            x = x / 107.0
            y = y / 71.0
            rich = np.stack(
                [0.08 + 0.82 * x, 0.10 + 0.72 * y, 0.12 + 0.70 * (1.0 - x)], axis=2
            )
            soft = np.clip(rich * 0.42 + 0.43, 0.0, 1.0)
            Image.fromarray(np.uint8(np.round(soft * 255.0)), mode="RGB").save(source)
            Image.fromarray(np.uint8(np.round(rich * 255.0)), mode="RGB").save(reference)
            source_hash = variants_script.sha256_file(source)
            report = search_reference_match(
                source,
                reference,
                self.neutral_path,
                "bold",
                output_dir,
                max_size=240,
                skin_protection=False,
            )
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["strength_grid"], list(STRENGTH_GRIDS["bold"]))
            self.assertEqual(len(report["candidates"]), 3)
            self.assertTrue(all(candidate["strength"] >= 0.8 for candidate in report["candidates"]))
            safe_distances = [
                candidate["match"]["output_distribution_distance"]
                for candidate in report["candidates"] if candidate["status"] == "safe"
            ]
            self.assertEqual(report["selected"]["match"]["output_distribution_distance"], min(safe_distances))
            self.assertEqual(source_hash, variants_script.sha256_file(source))
            self.assertTrue(Path(report["comparison_sheet"]).is_file())
            self.assertTrue(Path(report["selected"]["recipe"]).is_file())

    def test_black_point_mapping_does_not_create_colored_channel_zeros(self) -> None:
        recipe = load_recipe(self.neutral_path)
        recipe = copy.deepcopy(recipe)
        recipe["correction"]["black_point"] = 0.08
        recipe["correction"]["white_balance"]["rgb_gains"] = [0.85, 1.0, 1.18]
        source = np.full((20, 20, 3), [0.24, 0.18, 0.12], dtype=np.float32)
        output, _ = render_array(source, recipe)
        channel_is_zero = output[0, 0] <= 1.0 / 255.0
        self.assertIn(int(np.sum(channel_is_zero)), {0, 3})

    def test_schema_1_2_transformative_hue_range_is_smooth_and_selective(self) -> None:
        recipe = copy.deepcopy(load_recipe(self.neutral_path))
        recipe["schema_version"] = "1.2"
        recipe["strategy"] = {
            "intensity": "transformative",
            "style": "custom",
            "selection": "explicit",
        }
        recipe["look"]["hue_ranges"] = [{
            "label": "warm blossoms to pale violet",
            "center_degrees": 42.0,
            "width_degrees": 72.0,
            "feather_degrees": 24.0,
            "hue_shift_degrees": -118.0,
            "saturation_scale": 0.72,
            "luminance_scale": 1.0,
            "saturation_range": [0.04, 0.78],
            "luminance_range": [0.04, 0.95],
            "range_feather": 0.05,
            "strength": 0.92,
        }]
        recipe["protection"]["skin"] = {"enabled": False, "strength": 0.0}
        validate_recipe(recipe)
        source = np.zeros((24, 36, 3), dtype=np.float32)
        source[:, :18] = [0.82, 0.62, 0.42]
        source[:, 18:] = [0.52, 0.52, 0.52]
        output, _ = render_array(source, recipe)
        warm_output = output[:, :18].mean(axis=(0, 1))
        neutral_output = output[:, 18:].mean(axis=(0, 1))
        self.assertGreater(warm_output[2], warm_output[0])
        self.assertLess(float(np.max(np.abs(neutral_output - 0.52))), 0.01)

    def test_hue_ranges_require_schema_1_2_and_reject_unknown_operations(self) -> None:
        recipe = copy.deepcopy(load_recipe(self.neutral_path))
        recipe["look"]["hue_ranges"] = [{
            "center_degrees": 45.0,
            "width_degrees": 60.0,
            "hue_shift_degrees": -90.0,
        }]
        with self.assertRaises(RecipeError):
            validate_recipe(recipe)
        recipe["schema_version"] = "1.2"
        recipe["look"]["hue_ranges"][0]["semantic_mask"] = "flowers"
        with self.assertRaises(RecipeError):
            validate_recipe(recipe)

    def test_near_black_intent_tolerance_is_bounded_and_transformative_only(self) -> None:
        recipe = copy.deepcopy(load_recipe(self.transformative_path))
        validate_recipe(recipe)
        recipe["quality_tolerances"]["intentional_near_black_increase"] = 0.26
        with self.assertRaises(RecipeError):
            validate_recipe(recipe)
        recipe = copy.deepcopy(load_recipe(self.transformative_path))
        recipe["strategy"]["intensity"] = "bold"
        with self.assertRaises(RecipeError):
            validate_recipe(recipe)
        recipe = copy.deepcopy(load_recipe(self.transformative_path))
        recipe["quality_tolerances"]["reason"] = ""
        with self.assertRaises(RecipeError):
            validate_recipe(recipe)

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
