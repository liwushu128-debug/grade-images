# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import copy
import json
import sys
import tempfile
import types
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
import grade as grade_script  # noqa: E402
import preview as preview_script  # noqa: E402
import raw_check as raw_check_script  # noqa: E402
import route_documentary as route_documentary_script  # noqa: E402
import route_film as route_film_script  # noqa: E402
import variants as variants_script  # noqa: E402
from batch import derive_batch_recipes  # noqa: E402
from compare import (  # noqa: E402
    difference_metrics,
    gradient_metrics,
    reference_adjustment_suggestions,
    reference_match_metrics,
    strategy_warnings,
    texture_metrics,
    texture_warnings,
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
        cls.wabi_sabi_path = SKILL / "assets" / "recipes" / "wabi-sabi-deep-gray.json"
        cls.classic_negative_path = SKILL / "assets" / "recipes" / "classic-negative-standard.json"
        cls.daylight_disposable_path = SKILL / "assets" / "recipes" / "daylight-disposable-standard.json"
        cls.cinematic_print_path = SKILL / "assets" / "recipes" / "cinematic-print-standard.json"
        cls.documentary_vivid_path = SKILL / "assets" / "recipes" / "documentary-vivid-standard.json"
        cls.documentary_archive_path = SKILL / "assets" / "recipes" / "documentary-archive-standard.json"
        cls.documentary_earth_path = SKILL / "assets" / "recipes" / "documentary-earth-standard.json"
        cls.output_refine_path = SKILL / "assets" / "recipes" / "output-refine-standard.json"
        cls.documentary_vivid_refine_path = SKILL / "assets" / "recipes" / "documentary-vivid-refine.json"

    def test_bundled_recipes_validate(self) -> None:
        load_recipe(self.neutral_path)
        load_recipe(self.cinematic_path)
        load_recipe(self.low_light_path)
        load_recipe(self.natural_path)
        load_recipe(self.bold_path)
        load_recipe(self.soft_glow_path)
        load_recipe(self.transformative_path)
        load_recipe(self.wabi_sabi_path)
        load_recipe(self.classic_negative_path)
        load_recipe(self.daylight_disposable_path)
        load_recipe(self.cinematic_print_path)
        load_recipe(self.documentary_vivid_path)
        load_recipe(self.documentary_archive_path)
        load_recipe(self.documentary_earth_path)
        load_recipe(self.output_refine_path)
        load_recipe(self.documentary_vivid_refine_path)

    def test_generic_film_prompt_routes_to_three_color_only_variants(self) -> None:
        result = route_film_script.route_prompt("给这张照片标准强度的胶片感")
        self.assertEqual(result["mode"], "variants")
        self.assertEqual(result["default_intensity"], "standard")
        self.assertEqual(
            [candidate["id"] for candidate in result["candidates"]],
            ["classic-negative", "daylight-disposable", "cinematic-print"],
        )
        self.assertFalse(result["effect_requests"])
        for candidate in result["candidates"]:
            recipe = load_recipe(Path(candidate["recipe"]))
            self.assertNotIn("effects", recipe)
            self.assertEqual(recipe["preservation"]["mode"], "strict")
            self.assertFalse(recipe["preservation"]["allow_texture_changes"])

    def test_specific_film_prompts_route_deterministically(self) -> None:
        cases = {
            "晴天户外的一次性胶片快照": "daylight-disposable",
            "经典负片感的人像街拍": "classic-negative",
            "夜景要电影印片感": "cinematic-print",
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                result = route_film_script.route_prompt(prompt)
                self.assertEqual(result["mode"], "selected")
                self.assertEqual(result["candidates"][0]["id"], expected)

    def test_film_router_reports_forbidden_effects_without_enabling_them(self) -> None:
        result = route_film_script.route_prompt("一次性胶片感，加颗粒、暗角和漏光")
        self.assertEqual(result["candidates"][0]["id"], "daylight-disposable")
        self.assertEqual(
            {item["effect"] for item in result["effect_requests"]},
            {"grain", "vignette", "light_leak"},
        )
        recipe = load_recipe(Path(result["candidates"][0]["recipe"]))
        self.assertNotIn("effects", recipe)

    def test_film_color_catalog_uses_only_generic_product_language(self) -> None:
        catalog = (SKILL / "references" / "film-color-catalog.json").read_text(encoding="utf-8")
        routing = (SKILL / "references" / "film-color-routing.md").read_text(encoding="utf-8")
        recipes = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                self.classic_negative_path,
                self.daylight_disposable_path,
                self.cinematic_print_path,
            )
        )
        self.assertNotIn("dazz", (catalog + routing + recipes).casefold())

    def test_film_color_presets_are_visibly_distinct_and_structure_safe(self) -> None:
        source = np.full((64, 96, 3), [0.46, 0.46, 0.46], dtype=np.float32)
        source[:, :32] = [0.76, 0.42, 0.16]
        source[:, 64:] = [0.14, 0.46, 0.72]
        outputs = []
        for recipe_path in (
            self.classic_negative_path,
            self.daylight_disposable_path,
            self.cinematic_print_path,
        ):
            recipe = load_recipe(recipe_path)
            first, diagnostics = render_array(source, recipe)
            second, repeated_diagnostics = render_array(source, recipe)
            np.testing.assert_array_equal(first, second)
            self.assertEqual(diagnostics, repeated_diagnostics)
            structure = gradient_metrics(source, first)
            self.assertGreater(structure["strong_edge_orientation_agreement"], 0.98)
            self.assertLess(structure["new_strong_edge_fraction"], 0.012)
            difference = difference_metrics(source, first)
            self.assertGreater(difference["mean_absolute_rgb_delta"], 0.018)
            self.assertGreater(difference["p95_pixel_rgb_delta"], 0.045)
            outputs.append(first)
        for left in range(len(outputs)):
            for right in range(left + 1, len(outputs)):
                self.assertGreater(
                    difference_metrics(outputs[left], outputs[right])["mean_absolute_rgb_delta"],
                    0.006,
                )

    def test_generic_documentary_prompt_routes_to_two_color_only_variants(self) -> None:
        result = route_documentary_script.route_prompt("经典纪实摄影调色")
        self.assertEqual(result["mode"], "variants")
        self.assertEqual(result["default_intensity"], "standard")
        self.assertEqual(
            [candidate["id"] for candidate in result["candidates"]],
            ["documentary-vivid", "documentary-archive"],
        )
        for candidate in result["candidates"]:
            recipe = load_recipe(Path(candidate["recipe"]))
            self.assertNotIn("effects", recipe)
            self.assertEqual(recipe["preservation"]["mode"], "strict")
            self.assertFalse(recipe["preservation"]["allow_texture_changes"])

    def test_documentary_scene_routing_requires_documentary_language(self) -> None:
        self.assertEqual(route_documentary_script.route_prompt("帮我处理街头照片")["mode"], "not-applicable")
        vivid = route_documentary_script.route_prompt("经典纪实风光调色")
        archive = route_documentary_script.route_prompt("经典纪实街头调色")
        earth = route_documentary_script.route_prompt("经典纪实草原调色")
        self.assertEqual(vivid["candidates"][0]["id"], "documentary-vivid")
        self.assertEqual(archive["candidates"][0]["id"], "documentary-archive")
        self.assertEqual(earth["candidates"][0]["id"], "documentary-earth")

    def test_specific_documentary_profiles_route_deterministically(self) -> None:
        cases = {
            "这张照片做成高密度彩色纪实": "documentary-vivid",
            "这张照片做成档案纪实": "documentary-archive",
            "这张照片做成赭石纪实": "documentary-earth",
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                result = route_documentary_script.route_prompt(prompt)
                self.assertEqual(result["mode"], "selected")
                self.assertEqual(result["candidates"][0]["id"], expected)

    def test_documentary_router_reports_texture_and_detail_effects(self) -> None:
        result = route_documentary_script.route_prompt("经典纪实，加颗粒、灰尘和清晰度")
        self.assertEqual(
            {item["effect"] for item in result["effect_requests"]},
            {"grain", "dust", "clarity_dehaze"},
        )
        self.assertTrue(all("effects" not in load_recipe(Path(item["recipe"])) for item in result["candidates"]))

    def test_explicit_documentary_sharpen_is_separate_from_color_routing(self) -> None:
        result = route_documentary_script.route_prompt("经典纪实风光调色，并做输出锐化")
        self.assertEqual(result["candidates"][0]["id"], "documentary-vivid")
        self.assertEqual(result["texture_requests"][0]["operation"], "output_sharpen")
        self.assertEqual(result["texture_requests"][0]["status"], "eligible-after-source-review")
        self.assertNotIn("texture", load_recipe(Path(result["candidates"][0]["recipe"])))

    def test_film_sharpen_requires_a_separate_explicit_refine_route(self) -> None:
        result = route_film_script.route_prompt("胶片感，并做轻微输出锐化")
        self.assertTrue(result["texture_requests"])
        self.assertFalse(any(item["effect"] == "sharpen" for item in result["effect_requests"]))

    def test_schema_1_3_refine_is_explicit_bounded_and_non_generative(self) -> None:
        recipe = load_recipe(self.output_refine_path)
        self.assertTrue(recipe["preservation"]["allow_texture_changes"])
        self.assertFalse(recipe["preservation"]["allow_generative_changes"])
        self.assertEqual(recipe["texture"]["selection"], "explicit-user")
        for mutation in (
            lambda value: value.update({"schema_version": "1.2"}),
            lambda value: value["texture"].update({"permission": "none"}),
            lambda value: value["texture"]["output_sharpen"].update({"amount": 0.36}),
            lambda value: value["texture"].update({"denoise": {"enabled": True}}),
            lambda value: value["preservation"].update({"allow_generative_changes": True}),
        ):
            candidate = copy.deepcopy(recipe)
            mutation(candidate)
            with self.subTest(candidate=candidate):
                with self.assertRaises(RecipeError):
                    validate_recipe(candidate)

    def test_color_only_default_keeps_texture_disabled(self) -> None:
        recipe = load_recipe(self.neutral_path)
        source = np.linspace(0.1, 0.9, 96, dtype=np.float32)[None, :, None]
        source = np.tile(source, (64, 1, 3))
        result, diagnostics = render_array(source, recipe)
        np.testing.assert_allclose(result, source, atol=2e-6)
        self.assertEqual(diagnostics["texture"], {"enabled": False})

    def test_output_sharpen_is_deterministic_luminance_only_and_bounded(self) -> None:
        recipe = load_recipe(self.output_refine_path)
        source = np.full((72, 96, 3), 0.45, dtype=np.float32)
        source[:, 48:] = [0.68, 0.58, 0.48]
        source[::4, :, :] += 0.025
        source = np.clip(source, 0.0, 1.0)
        first, diagnostics = render_array(source, recipe)
        second, repeated = render_array(source, recipe)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(diagnostics, repeated)
        self.assertTrue(diagnostics["texture"]["enabled"])
        self.assertLessEqual(diagnostics["texture"]["maximum_luma_delta"], 0.035)
        source_chroma = source - np.mean(source, axis=2, keepdims=True)
        output_chroma = first - np.mean(first, axis=2, keepdims=True)
        np.testing.assert_allclose(output_chroma, source_chroma, atol=2e-6)
        metrics = texture_metrics(source, first)
        self.assertGreater(metrics["mean_gradient_ratio"], 1.0)
        self.assertFalse(texture_warnings(recipe, metrics))

    def test_documentary_presets_are_distinct_safe_and_keep_signature_yellow(self) -> None:
        source = np.full((64, 96, 3), [0.46, 0.46, 0.46], dtype=np.float32)
        source[:, :32] = [0.78, 0.58, 0.08]
        source[:, 64:] = [0.12, 0.42, 0.68]
        outputs = []
        for recipe_path in (self.documentary_vivid_path, self.documentary_archive_path):
            recipe = load_recipe(recipe_path)
            first, diagnostics = render_array(source, recipe)
            second, repeated_diagnostics = render_array(source, recipe)
            np.testing.assert_array_equal(first, second)
            self.assertEqual(diagnostics, repeated_diagnostics)
            self.assertGreater(gradient_metrics(source, first)["strong_edge_orientation_agreement"], 0.98)
            self.assertLess(gradient_metrics(source, first)["new_strong_edge_fraction"], 0.012)
            difference = difference_metrics(source, first)
            self.assertGreater(difference["mean_absolute_rgb_delta"], 0.018)
            self.assertGreater(difference["p95_pixel_rgb_delta"], 0.045)
            outputs.append(first)
        self.assertGreater(difference_metrics(outputs[0], outputs[1])["mean_absolute_rgb_delta"], 0.012)
        vivid_yellow = np.mean(outputs[0][:, :32], axis=(0, 1))
        self.assertGreater(float(min(vivid_yellow[0], vivid_yellow[1]) - vivid_yellow[2]), 0.25)

    def test_documentary_earth_selectively_moves_established_green_toward_ochre(self) -> None:
        recipe = load_recipe(self.documentary_earth_path)
        source = np.full((32, 64, 3), [0.18, 0.62, 0.2], dtype=np.float32)
        source[:, 32:] = [0.45, 0.45, 0.45]
        output, _ = render_array(source, recipe)
        green_source = np.mean(source[:, :32], axis=(0, 1))
        green_output = np.mean(output[:, :32], axis=(0, 1))
        neutral_delta = float(np.mean(np.abs(output[:, 32:] - source[:, 32:])))
        green_delta = float(np.mean(np.abs(output[:, :32] - source[:, :32])))
        self.assertGreater(green_output[0] / green_output[1], green_source[0] / green_source[1])
        self.assertGreater(green_delta, neutral_delta)
        self.assertGreater(gradient_metrics(source, output)["strong_edge_orientation_agreement"], 0.98)

    def test_wabi_sabi_preset_darkens_base_and_retains_warm_color_hierarchy(self) -> None:
        recipe = load_recipe(self.wabi_sabi_path)
        source = np.zeros((24, 48, 3), dtype=np.float32)
        source[:, :24] = [0.68, 0.46, 0.27]
        source[:, 24:] = [0.27, 0.46, 0.68]
        output, _ = render_array(source, recipe)
        warm = output[:, :24].mean(axis=(0, 1))
        cool = output[:, 24:].mean(axis=(0, 1))
        warm_saturation = (float(np.max(warm)) - float(np.min(warm))) / float(np.max(warm))
        cool_saturation = (float(np.max(cool)) - float(np.min(cool))) / float(np.max(cool))
        self.assertLess(float(np.mean(output)), float(np.mean(source)))
        self.assertGreater(warm_saturation, cool_saturation)

    def test_wabi_sabi_preset_handles_diverse_synthetic_scenes(self) -> None:
        recipe = load_recipe(self.wabi_sabi_path)
        ramp = np.linspace(0.04, 0.92, 96, dtype=np.float32)
        grayscale = np.repeat(np.repeat(ramp[None, :, None], 64, axis=0), 3, axis=2)

        bright_mixed = np.full((64, 96, 3), [0.72, 0.72, 0.68], dtype=np.float32)
        bright_mixed[:, :32] = [0.78, 0.48, 0.20]
        bright_mixed[:, 32:64] = [0.20, 0.48, 0.78]

        cool_dominant = np.full((64, 96, 3), [0.18, 0.42, 0.68], dtype=np.float32)
        cool_dominant[16:48, 36:60] = [0.72, 0.43, 0.18]

        low_light = np.full((64, 96, 3), [0.035, 0.045, 0.055], dtype=np.float32)
        low_light[20:44, 34:62] = [0.22, 0.14, 0.07]
        low_light[28:36, 44:52] = [0.76, 0.63, 0.42]

        highlight_limited = np.full((64, 96, 3), [0.30, 0.33, 0.35], dtype=np.float32)
        highlight_limited[20:36, 40:56] = [0.98, 0.92, 0.82]

        cases = {
            "grayscale-ramp": grayscale,
            "bright-mixed": bright_mixed,
            "cool-dominant": cool_dominant,
            "low-light": low_light,
            "highlight-limited": highlight_limited,
        }
        for name, source in cases.items():
            with self.subTest(name=name):
                output, diagnostics = render_array(source, recipe)
                source_analysis = analyze_script.analyze_array(source)
                output_analysis = analyze_script.analyze_array(output)
                structure = gradient_metrics(source, output)
                self.assertEqual(output.shape, source.shape)
                self.assertTrue(np.all(np.isfinite(output)))
                self.assertGreater(structure["strong_edge_orientation_agreement"], 0.98)
                self.assertLess(structure["new_strong_edge_fraction"], 0.01)
                self.assertLessEqual(
                    output_analysis["clipping"]["any_channel_high_fraction"],
                    source_analysis["clipping"]["any_channel_high_fraction"] + 0.005,
                )
                self.assertLessEqual(
                    output_analysis["saturation"]["extreme_fraction"],
                    source_analysis["saturation"]["extreme_fraction"] + 0.01,
                )
                self.assertLess(diagnostics["gamut_compressed_fraction"], 0.05)

        gray_output, _ = render_array(grayscale, recipe)
        gray_channel_means = np.mean(gray_output, axis=(0, 1))
        self.assertLess(float(np.max(gray_channel_means) - np.min(gray_channel_means)), 0.04)

        low_output, _ = render_array(low_light, recipe)
        low_source_black = analyze_script.analyze_array(low_light)["clipping"]["near_black_fraction"]
        low_output_black = analyze_script.analyze_array(low_output)["clipping"]["near_black_fraction"]
        self.assertLessEqual(low_output_black, low_source_black + 0.10)

    def test_all_bundled_presets_are_deterministic_across_scene_matrix(self) -> None:
        ramp = np.linspace(0.03, 0.97, 96, dtype=np.float32)
        grayscale = np.repeat(np.repeat(ramp[None, :, None], 64, axis=0), 3, axis=2)

        warm_cool = np.full((64, 96, 3), [0.48, 0.48, 0.48], dtype=np.float32)
        warm_cool[:, :32] = [0.82, 0.48, 0.16]
        warm_cool[:, 64:] = [0.16, 0.48, 0.82]

        low_light = np.full((64, 96, 3), [0.02, 0.035, 0.05], dtype=np.float32)
        low_light[18:46, 28:68] = [0.20, 0.12, 0.06]
        low_light[28:36, 44:52] = [0.82, 0.68, 0.44]

        high_contrast = np.full((64, 96, 3), [0.12, 0.14, 0.16], dtype=np.float32)
        high_contrast[:, 48:] = [0.72, 0.76, 0.80]
        high_contrast[20:44, 38:58] = [0.99, 0.94, 0.84]

        rng = np.random.default_rng(20260805)
        near_neutral = np.clip(
            np.full((64, 96, 3), 0.46, dtype=np.float32)
            + rng.normal(0.0, 0.008, (64, 96, 3)).astype(np.float32),
            0.0,
            1.0,
        )

        samples = {
            "grayscale": grayscale,
            "warm-cool": warm_cool,
            "low-light": low_light,
            "high-contrast": high_contrast,
            "near-neutral": near_neutral,
        }
        recipe_paths = [
            self.neutral_path,
            self.cinematic_path,
            self.low_light_path,
            self.natural_path,
            self.bold_path,
            self.soft_glow_path,
            self.transformative_path,
            self.wabi_sabi_path,
            self.classic_negative_path,
            self.daylight_disposable_path,
            self.cinematic_print_path,
            self.documentary_vivid_path,
            self.documentary_archive_path,
            self.documentary_earth_path,
        ]
        for recipe_path in recipe_paths:
            recipe = load_recipe(recipe_path)
            glow_enabled = recipe.get("effects", {}).get("source_glow", {}).get("enabled", False)
            new_edge_limit = 0.04 if glow_enabled else 0.01
            for sample_name, source in samples.items():
                with self.subTest(recipe=recipe_path.name, sample=sample_name):
                    first, first_diagnostics = render_array(source, recipe)
                    second, second_diagnostics = render_array(source, recipe)
                    np.testing.assert_array_equal(first, second)
                    self.assertEqual(first_diagnostics, second_diagnostics)
                    self.assertEqual(first.shape, source.shape)
                    self.assertTrue(np.all(np.isfinite(first)))
                    self.assertGreaterEqual(float(np.min(first)), 0.0)
                    self.assertLessEqual(float(np.max(first)), 1.0)
                    structure = gradient_metrics(source, first)
                    self.assertGreater(structure["strong_edge_orientation_agreement"], 0.98)
                    self.assertLessEqual(structure["new_strong_edge_fraction"], new_edge_limit)

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

    def test_low_light_reference_match_fits_multiple_tonal_landmarks(self) -> None:
        template = load_recipe(self.neutral_path)
        y, x = np.mgrid[0:80, 0:120]
        base = 0.01 + 0.16 * (x / 119.0) ** 2
        source = np.repeat(base[..., None], 3, axis=2).astype(np.float32)
        source[15:30, 85:105] = 0.72
        reference = np.clip(source ** 0.88, 0.0, 1.0).astype(np.float32)
        recipe, diagnostics = derive_match_recipe(
            source, reference, template, strength=0.90, skin_protection=False
        )
        output, _ = render_array(source, recipe)
        metrics = reference_match_metrics(
            analyze_script.analyze_array(source),
            analyze_script.analyze_array(output),
            analyze_script.analyze_array(reference),
        )
        self.assertEqual(
            diagnostics["exposure_fit_percentiles"],
            ["p05", "p25", "p50", "p75", "p95"],
        )
        self.assertLess(diagnostics["exposure_delta_ev"], diagnostics["exposure_limit_ev"])
        self.assertTrue(diagnostics["low_light_positive_curve_suppressed"])
        self.assertGreater(metrics["tone_improvement_fraction"], 0.50)

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

        globally_underpowered = {
            "mean_absolute_rgb_delta": 0.014,
            "p95_pixel_rgb_delta": 0.06,
            "mean_absolute_luma_delta": 0.01,
            "changed_pixel_fraction_2_255": 0.65,
        }
        self.assertTrue(
            any("standard strategy" in item for item in strategy_warnings(standard, globally_underpowered))
        )

        localized = copy.deepcopy(standard)
        localized["schema_version"] = "1.2"
        localized["look"]["hue_ranges"] = [{
            "center_degrees": 40.0,
            "width_degrees": 60.0,
            "hue_shift_degrees": -80.0,
        }]
        self.assertFalse(strategy_warnings(localized, globally_underpowered))

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

            strict_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            strict_manifest["cases"][0]["minimum_tone_improvement_fraction"] = 1.1
            strict_path = root / "strict-cases.json"
            strict_path.write_text(json.dumps(strict_manifest), encoding="utf-8")
            strict_report = run_regression(strict_path, root / "strict-regression")
            self.assertEqual(strict_report["status"], "fail")
            self.assertTrue(any(
                "tone improvement" in failure
                for failure in strict_report["cases"][0]["failures"]
            ))

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

    def test_overlapping_hue_ranges_are_order_independent(self) -> None:
        recipe = copy.deepcopy(load_recipe(self.neutral_path))
        recipe["schema_version"] = "1.2"
        recipe["strategy"] = {
            "intensity": "bold",
            "style": "custom",
            "selection": "explicit",
        }
        first = {
            "label": "warm family cooler",
            "center_degrees": 42.0,
            "width_degrees": 100.0,
            "feather_degrees": 30.0,
            "hue_shift_degrees": -55.0,
            "saturation_scale": 0.8,
            "luminance_scale": 0.95,
            "saturation_range": [0.03, 1.0],
            "luminance_range": [0.01, 0.99],
            "range_feather": 0.04,
            "strength": 0.72,
        }
        second = {
            "label": "yellow family restrained",
            "center_degrees": 68.0,
            "width_degrees": 80.0,
            "feather_degrees": 24.0,
            "hue_shift_degrees": -18.0,
            "saturation_scale": 0.55,
            "luminance_scale": 0.88,
            "saturation_range": [0.03, 1.0],
            "luminance_range": [0.01, 0.99],
            "range_feather": 0.04,
            "strength": 0.64,
        }
        source = np.zeros((20, 30, 3), dtype=np.float32)
        source[:, :10] = [0.78, 0.55, 0.24]
        source[:, 10:20] = [0.68, 0.42, 0.21]
        source[:, 20:] = [0.32, 0.48, 0.72]
        recipe["look"]["hue_ranges"] = [first, second]
        forward, _ = render_array(source, recipe)
        recipe["look"]["hue_ranges"] = [second, first]
        reverse, _ = render_array(source, recipe)
        np.testing.assert_allclose(forward, reverse, atol=1e-6)

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

    def test_raw_input_requires_optional_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "camera-file.dng"
            path.write_bytes(b"fake raw fixture")
            with patch.dict(sys.modules, {"rawpy": None}):
                with self.assertRaisesRegex(RecipeError, "requirements-raw.txt"):
                    load_image(path)

    def test_raw_decoder_uses_recorded_strict_development_contract(self) -> None:
        calls = {}

        class FakeRaw:
            sizes = types.SimpleNamespace(width=40, height=30, flip=0)
            camera_whitebalance = [2.0, 1.0, 1.5, 1.0]
            auto_whitebalance = [2.0, 1.0, 1.5, 1.0]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def postprocess(self, **kwargs):
                calls.update(kwargs)
                ramp = np.linspace(0, 65535, 40, dtype=np.uint16)
                return np.repeat(np.repeat(ramp[None, :, None], 30, axis=0), 3, axis=2)

        class FakeLibRawError(Exception):
            pass

        fake_rawpy = types.SimpleNamespace(
            __version__="0.27.0",
            libraw_version=(0, 22, 1),
            imread=lambda path: FakeRaw(),
            DemosaicAlgorithm=types.SimpleNamespace(AHD=3),
            ColorSpace=types.SimpleNamespace(sRGB=1),
            FBDDNoiseReductionMode=types.SimpleNamespace(Off=0),
            HighlightMode=types.SimpleNamespace(Clip=0),
            LibRawError=FakeLibRawError,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.dng"
            output = Path(directory) / "result.png"
            path.write_bytes(b"fake raw fixture")
            with patch.dict(sys.modules, {"rawpy": fake_rawpy}):
                rgb, alpha, metadata = load_image(path)
                self.assertEqual(
                    grade_script.render_command(path, self.neutral_path, output, None), 0
                )
            manifest = json.loads(
                output.with_suffix(".png.manifest.json").read_text(encoding="utf-8")
            )

        self.assertIsNone(alpha)
        self.assertEqual(rgb.shape, (30, 40, 3))
        self.assertEqual(rgb.dtype, np.float32)
        self.assertAlmostEqual(float(np.max(rgb)), 1.0)
        self.assertEqual(metadata["source_mode"], "RAW")
        self.assertEqual(metadata["source_size"], (40, 30))
        self.assertEqual(metadata["color_management"], "rawpy_libraw_camera_to_srgb")
        self.assertEqual(metadata["raw_development"]["output_bps"], 16)
        self.assertEqual(metadata["raw_development"]["graded_derivative_bps"], 8)
        self.assertEqual(metadata["raw_development"]["libraw_version"], "0.22.1")
        self.assertTrue(metadata["raw_development"]["camera_white_balance_valid"])
        self.assertEqual(metadata["raw_development"]["camera_white_balance_status"], "valid")
        self.assertEqual(metadata["raw_development"]["white_balance_source"], "camera")
        self.assertEqual(metadata["raw_development"]["demosaic_algorithm"], "AHD")
        self.assertEqual(
            metadata["raw_development"]["detail_operations"]["fbdd_noise_reduction"],
            "off",
        )
        self.assertEqual(manifest["raw_development"]["backend"], "rawpy/LibRaw")
        self.assertEqual(calls["demosaic_algorithm"], 3)
        self.assertTrue(calls["use_camera_wb"])
        self.assertFalse(calls["use_auto_wb"])
        self.assertIsNone(calls["user_wb"])
        self.assertTrue(calls["no_auto_bright"])
        self.assertEqual(calls["gamma"], (2.4, 12.92))
        self.assertFalse(calls["half_size"])
        self.assertEqual(calls["highlight_mode"], 0)
        self.assertFalse(calls["four_color_rgb"])
        self.assertEqual(calls["dcb_iterations"], 0)
        self.assertFalse(calls["dcb_enhance"])
        self.assertEqual(calls["fbdd_noise_reduction"], 0)
        self.assertIsNone(calls["noise_thr"])
        self.assertEqual(calls["median_filter_passes"], 0)
        self.assertIsNone(calls["chromatic_aberration"])
        self.assertIsNone(calls["bad_pixels_path"])
        self.assertEqual(manifest["output_encoding"]["png_compress_level"], 2)
        self.assertTrue(manifest["output_encoding"]["lossless"])
        self.assertIn("load_and_raw_develop", manifest["timing_seconds"])
        self.assertIn("save", manifest["timing_seconds"])

    def test_raw_identity_camera_wb_falls_back_to_daylight_coefficients(self) -> None:
        calls = {}

        class FakeRaw:
            sizes = types.SimpleNamespace(width=20, height=10, flip=3)
            camera_whitebalance = [1.0, 1.0, 1.0, 1.0]
            daylight_whitebalance = [2.2, 1.0, 1.6, 0.0]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def postprocess(self, **kwargs):
                calls.update(kwargs)
                return np.full((10, 20, 3), 120, dtype=np.uint8)

        fake_rawpy = types.SimpleNamespace(
            __version__="test",
            libraw_version=(0, 22, 1),
            imread=lambda path: FakeRaw(),
            DemosaicAlgorithm=types.SimpleNamespace(AHD=3),
            ColorSpace=types.SimpleNamespace(sRGB=1),
            FBDDNoiseReductionMode=types.SimpleNamespace(Off=0),
            HighlightMode=types.SimpleNamespace(Clip=0),
            LibRawError=RuntimeError,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.nef"
            path.write_bytes(b"fake raw fixture")
            with patch.dict(sys.modules, {"rawpy": fake_rawpy}):
                _, _, metadata = load_image(path)

        development = metadata["raw_development"]
        self.assertFalse(calls["use_camera_wb"])
        self.assertEqual(calls["user_wb"], [2.2, 1.0, 1.6, 1.0])
        self.assertEqual(development["camera_white_balance_status"], "identity_suspect")
        self.assertFalse(development["camera_white_balance_valid"])
        self.assertEqual(development["daylight_white_balance_status"], "valid")
        self.assertEqual(development["white_balance_source"], "daylight")
        self.assertEqual(
            development["white_balance_fallback_reason"],
            "camera_white_balance_identity_suspect",
        )
        self.assertEqual(development["orientation_flip"], 3)
        self.assertTrue(any("daylight coefficients" in item for item in metadata["warnings"]))

    def test_raw_missing_white_balance_records_decoder_default(self) -> None:
        calls = {}

        class FakeRaw:
            sizes = types.SimpleNamespace(width=16, height=12, flip=0)
            camera_whitebalance = None
            daylight_whitebalance = [0.0, 1.0, 1.0, 1.0]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def postprocess(self, **kwargs):
                calls.update(kwargs)
                return np.full((12, 16, 3), 100, dtype=np.uint8)

        fake_rawpy = types.SimpleNamespace(
            __version__="test",
            libraw_version=(0, 22, 1),
            imread=lambda path: FakeRaw(),
            DemosaicAlgorithm=types.SimpleNamespace(AHD=3),
            ColorSpace=types.SimpleNamespace(sRGB=1),
            FBDDNoiseReductionMode=types.SimpleNamespace(Off=0),
            HighlightMode=types.SimpleNamespace(Clip=0),
            LibRawError=RuntimeError,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.dng"
            path.write_bytes(b"fake raw fixture")
            with patch.dict(sys.modules, {"rawpy": fake_rawpy}):
                _, _, metadata = load_image(path)

        development = metadata["raw_development"]
        self.assertFalse(calls["use_camera_wb"])
        self.assertIsNone(calls["user_wb"])
        self.assertEqual(development["camera_white_balance_status"], "missing")
        self.assertEqual(development["daylight_white_balance_status"], "invalid")
        self.assertEqual(development["white_balance_source"], "decoder_default")
        self.assertTrue(any("decoder defaults" in item for item in metadata["warnings"]))

    def test_raw_preview_uses_half_size_and_one_bounded_resize(self) -> None:
        calls = {}

        class FakeRaw:
            sizes = types.SimpleNamespace(width=400, height=300, flip=0)
            camera_whitebalance = [1.8, 1.0, 1.4, 1.0]
            auto_whitebalance = [1.8, 1.0, 1.4, 1.0]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def postprocess(self, **kwargs):
                calls.update(kwargs)
                return np.full((150, 200, 3), 128, dtype=np.uint8)

        fake_rawpy = types.SimpleNamespace(
            __version__="test",
            libraw_version=(0, 22, 1),
            imread=lambda path: FakeRaw(),
            DemosaicAlgorithm=types.SimpleNamespace(AHD=3),
            ColorSpace=types.SimpleNamespace(sRGB=1),
            FBDDNoiseReductionMode=types.SimpleNamespace(Off=0),
            HighlightMode=types.SimpleNamespace(Clip=0),
            LibRawError=RuntimeError,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.nef"
            path.write_bytes(b"fake raw fixture")
            with patch.dict(sys.modules, {"rawpy": fake_rawpy}):
                rgb, _, metadata = load_image(path, max_size=100)

        self.assertTrue(calls["half_size"])
        self.assertEqual(calls["output_bps"], 8)
        self.assertEqual(rgb.shape, (75, 100, 3))
        self.assertEqual(metadata["source_size"], (400, 300))
        self.assertTrue(metadata["raw_development"]["half_size"])

    def test_unsupported_raw_camera_fails_closed(self) -> None:
        class FakeLibRawError(Exception):
            pass

        fake_rawpy = types.SimpleNamespace(
            imread=lambda path: (_ for _ in ()).throw(FakeLibRawError("unsupported camera")),
            LibRawError=FakeLibRawError,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "camera.cr3"
            path.write_bytes(b"unsupported raw fixture")
            with patch.dict(sys.modules, {"rawpy": fake_rawpy}):
                with self.assertRaisesRegex(RecipeError, "unsupported camera"):
                    load_image(path)

    def test_raw_check_records_determinism_full_decode_and_unchanged_source(self) -> None:
        class FakeRaw:
            sizes = types.SimpleNamespace(width=160, height=120, flip=0)
            camera_whitebalance = [2.0, 1.0, 1.4, 1.0]
            auto_whitebalance = [2.0, 1.0, 1.4, 1.0]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def postprocess(self, **kwargs):
                dtype = np.uint16 if kwargs["output_bps"] == 16 else np.uint8
                maximum = 65535 if dtype == np.uint16 else 255
                return np.full((120, 160, 3), maximum // 2, dtype=dtype)

        fake_rawpy = types.SimpleNamespace(
            __version__="0.27.0",
            libraw_version=(0, 22, 1),
            imread=lambda path: FakeRaw(),
            DemosaicAlgorithm=types.SimpleNamespace(AHD=3),
            ColorSpace=types.SimpleNamespace(sRGB=1),
            FBDDNoiseReductionMode=types.SimpleNamespace(Off=0),
            HighlightMode=types.SimpleNamespace(Clip=0),
            LibRawError=RuntimeError,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.nef"
            report_path = root / "raw-check.json"
            source.write_bytes(b"unchanged raw fixture")
            with patch.dict(sys.modules, {"rawpy": fake_rawpy}):
                report = raw_check_script.run_raw_checks(
                    [source], report_path, max_size=100, full_decode=True
                )

            self.assertEqual(report["status"], "pass")
            case = report["cases"][0]
            self.assertTrue(case["deterministic_preview"])
            self.assertTrue(case["source_unchanged"])
            self.assertEqual(case["full_decode"]["decoder_output_bps"], 16)
            self.assertTrue(report_path.is_file())

    def test_raw_check_can_require_valid_camera_white_balance(self) -> None:
        class FakeRaw:
            sizes = types.SimpleNamespace(width=20, height=10, flip=0)
            camera_whitebalance = [1.0, 1.0, 1.0, 1.0]
            daylight_whitebalance = [2.0, 1.0, 1.5, 1.0]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def postprocess(self, **kwargs):
                return np.full((10, 20, 3), 128, dtype=np.uint8)

        fake_rawpy = types.SimpleNamespace(
            __version__="test",
            libraw_version=(0, 22, 1),
            imread=lambda path: FakeRaw(),
            DemosaicAlgorithm=types.SimpleNamespace(AHD=3),
            ColorSpace=types.SimpleNamespace(sRGB=1),
            FBDDNoiseReductionMode=types.SimpleNamespace(Off=0),
            HighlightMode=types.SimpleNamespace(Clip=0),
            LibRawError=RuntimeError,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.nef"
            source.write_bytes(b"unchanged raw fixture")
            with patch.dict(sys.modules, {"rawpy": fake_rawpy}):
                report = raw_check_script.run_raw_checks(
                    [source],
                    root / "raw-check.json",
                    require_camera_wb=True,
                )

        self.assertTrue(report["require_camera_wb"])
        self.assertEqual(report["status"], "fail")
        self.assertIn("daylight", report["cases"][0]["error"])

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
