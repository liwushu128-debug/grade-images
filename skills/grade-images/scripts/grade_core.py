# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageCms, ImageFilter


class RecipeError(ValueError):
    pass


TOP_KEYS = {
    "schema_version",
    "intent",
    "strategy",
    "preservation",
    "correction",
    "look",
    "effects",
    "texture",
    "protection",
    "quality_tolerances",
    "output",
}

RAW_EXTENSIONS = {
    ".3fr", ".ari", ".arw", ".bay", ".crw", ".cr2", ".cr3", ".dcr",
    ".dng", ".erf", ".fff", ".gpr", ".iiq", ".k25", ".kdc", ".mef",
    ".mos", ".mrw", ".nef", ".nrw", ".orf", ".pef", ".raf", ".raw",
    ".rwl", ".rw2", ".sr2", ".srf", ".srw", ".x3f",
}


def _srgb_profile_bytes() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RecipeError(f"{name} must be an object")
    return value


def _only_keys(value: dict[str, Any], allowed: set[str], name: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise RecipeError(f"{name} contains unknown or forbidden keys: {sorted(unknown)}")


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecipeError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        raise RecipeError(f"{name} must be in [{low}, {high}]")
    return result


def _triplet(value: Any, name: str, low: float, high: float) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise RecipeError(f"{name} must contain three numbers")
    return [_number(item, f"{name}[{index}]", low, high) for index, item in enumerate(value)]


def validate_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(recipe, dict):
        raise RecipeError("recipe must be a JSON object")
    _only_keys(recipe, TOP_KEYS, "recipe")
    schema_version = recipe.get("schema_version")
    if schema_version not in {"1.0", "1.1", "1.2", "1.3"}:
        raise RecipeError("schema_version must be '1.0', '1.1', '1.2', or '1.3'")
    if not isinstance(recipe.get("intent", ""), str):
        raise RecipeError("intent must be a string")

    strategy = _object(recipe.get("strategy"), "strategy")
    _only_keys(strategy, {"intensity", "style", "selection"}, "strategy")
    if strategy:
        if strategy.get("intensity") not in {"conservative", "standard", "bold", "transformative"}:
            raise RecipeError(
                "strategy.intensity must be conservative, standard, bold, or transformative"
            )
        if strategy.get("style") not in {"technical", "natural", "cinematic", "reference", "custom"}:
            raise RecipeError("strategy.style must be technical, natural, cinematic, reference, or custom")
        if strategy.get("selection") not in {"explicit", "inferred", "default-standard", "template"}:
            raise RecipeError("strategy.selection must be explicit, inferred, default-standard, or template")

    preservation = _object(recipe.get("preservation"), "preservation")
    _only_keys(
        preservation,
        {"mode", "allow_geometry_changes", "allow_texture_changes", "allow_generative_changes"},
        "preservation",
    )
    texture_preview = _object(recipe.get("texture"), "texture")
    sharpen_preview = _object(texture_preview.get("output_sharpen"), "texture.output_sharpen")
    texture_requested = bool(sharpen_preview.get("enabled", False))
    required_policy = {
        "mode": "strict",
        "allow_geometry_changes": False,
        "allow_texture_changes": texture_requested,
        "allow_generative_changes": False,
    }
    if preservation != required_policy:
        raise RecipeError(
            "strict preservation is required; allow_texture_changes may be true only for an enabled v0.3.4 refine block"
        )

    correction = _object(recipe.get("correction"), "correction")
    _only_keys(
        correction,
        {"exposure_ev", "white_balance", "black_point", "white_point", "highlight_rolloff"},
        "correction",
    )
    _number(correction.get("exposure_ev", 0.0), "correction.exposure_ev", -3.0, 3.0)
    black = _number(correction.get("black_point", 0.0), "correction.black_point", 0.0, 0.2)
    white = _number(correction.get("white_point", 1.0), "correction.white_point", 0.8, 1.5)
    if white <= black:
        raise RecipeError("correction.white_point must exceed black_point")
    _number(correction.get("highlight_rolloff", 0.0), "correction.highlight_rolloff", 0.0, 1.0)
    white_balance = _object(correction.get("white_balance"), "correction.white_balance")
    _only_keys(white_balance, {"rgb_gains"}, "correction.white_balance")
    _triplet(white_balance.get("rgb_gains", [1.0, 1.0, 1.0]), "correction.white_balance.rgb_gains", 0.5, 2.0)

    look = _object(recipe.get("look"), "look")
    _only_keys(
        look,
        {"tone_curve", "cdl", "saturation", "vibrance", "split_tone", "hue_ranges"},
        "look",
    )
    tone_curve = _object(look.get("tone_curve"), "look.tone_curve")
    _only_keys(tone_curve, {"strength"}, "look.tone_curve")
    _number(tone_curve.get("strength", 0.0), "look.tone_curve.strength", -1.0, 1.0)
    cdl = _object(look.get("cdl"), "look.cdl")
    _only_keys(cdl, {"slope", "offset", "power", "saturation"}, "look.cdl")
    _triplet(cdl.get("slope", [1.0, 1.0, 1.0]), "look.cdl.slope", 0.25, 4.0)
    _triplet(cdl.get("offset", [0.0, 0.0, 0.0]), "look.cdl.offset", -0.25, 0.25)
    _triplet(cdl.get("power", [1.0, 1.0, 1.0]), "look.cdl.power", 0.25, 4.0)
    cdl_saturation = _number(cdl.get("saturation", 1.0), "look.cdl.saturation", 0.0, 2.0)
    global_saturation = _number(look.get("saturation", 1.0), "look.saturation", 0.0, 2.0)
    vibrance = _number(look.get("vibrance", 0.0), "look.vibrance", -1.0, 2.0)
    adjusted_chroma_controls = sum(
        (
            not math.isclose(cdl_saturation, 1.0),
            not math.isclose(global_saturation, 1.0),
            not math.isclose(vibrance, 0.0),
        )
    )
    if adjusted_chroma_controls > 1:
        raise RecipeError(
            "set only one chroma control: cdl.saturation, saturation, or vibrance"
        )
    if not math.isclose(vibrance, 0.0) and schema_version not in {"1.1", "1.2", "1.3"}:
        raise RecipeError("look.vibrance requires schema_version '1.1', '1.2', or '1.3'")
    split = _object(look.get("split_tone"), "look.split_tone")
    _only_keys(split, {"shadows", "highlights", "balance", "strength"}, "look.split_tone")
    _triplet(split.get("shadows", [0.5, 0.5, 0.5]), "look.split_tone.shadows", 0.0, 1.0)
    _triplet(split.get("highlights", [0.5, 0.5, 0.5]), "look.split_tone.highlights", 0.0, 1.0)
    _number(split.get("balance", 0.0), "look.split_tone.balance", -1.0, 1.0)
    _number(split.get("strength", 0.0), "look.split_tone.strength", 0.0, 0.25)

    hue_ranges = look.get("hue_ranges", [])
    if not isinstance(hue_ranges, list):
        raise RecipeError("look.hue_ranges must be an array")
    if hue_ranges and schema_version not in {"1.2", "1.3"}:
        raise RecipeError("look.hue_ranges requires schema_version '1.2' or '1.3'")
    if len(hue_ranges) > 8:
        raise RecipeError("look.hue_ranges supports at most 8 ranges")
    for index, value in enumerate(hue_ranges):
        name = f"look.hue_ranges[{index}]"
        item = _object(value, name)
        _only_keys(
            item,
            {
                "label",
                "center_degrees",
                "width_degrees",
                "feather_degrees",
                "hue_shift_degrees",
                "saturation_scale",
                "luminance_scale",
                "saturation_range",
                "luminance_range",
                "range_feather",
                "strength",
            },
            name,
        )
        if "label" in item and not isinstance(item["label"], str):
            raise RecipeError(f"{name}.label must be a string")
        _number(item.get("center_degrees"), f"{name}.center_degrees", 0.0, 360.0)
        width = _number(item.get("width_degrees"), f"{name}.width_degrees", 1.0, 180.0)
        feather = _number(item.get("feather_degrees", 0.0), f"{name}.feather_degrees", 0.0, 90.0)
        if feather > width:
            raise RecipeError(f"{name}.feather_degrees must not exceed width_degrees")
        _number(item.get("hue_shift_degrees", 0.0), f"{name}.hue_shift_degrees", -180.0, 180.0)
        _number(item.get("saturation_scale", 1.0), f"{name}.saturation_scale", 0.0, 2.0)
        _number(item.get("luminance_scale", 1.0), f"{name}.luminance_scale", 0.25, 2.0)
        for field in ("saturation_range", "luminance_range"):
            bounds = item.get(field, [0.0, 1.0])
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise RecipeError(f"{name}.{field} must contain two numbers")
            low = _number(bounds[0], f"{name}.{field}[0]", 0.0, 1.0)
            high = _number(bounds[1], f"{name}.{field}[1]", 0.0, 1.0)
            if high <= low:
                raise RecipeError(f"{name}.{field}[1] must exceed {field}[0]")
        _number(item.get("range_feather", 0.05), f"{name}.range_feather", 0.0, 0.25)
        _number(item.get("strength", 1.0), f"{name}.strength", 0.0, 1.0)

    effects = _object(recipe.get("effects"), "effects")
    if "effects" in recipe and schema_version not in {"1.1", "1.2", "1.3"}:
        raise RecipeError("effects require schema_version '1.1', '1.2', or '1.3'")
    _only_keys(effects, {"permission", "selection", "source_glow"}, "effects")
    source_glow = _object(effects.get("source_glow"), "effects.source_glow")
    _only_keys(
        source_glow,
        {"enabled", "threshold", "knee", "radius_fraction", "strength"},
        "effects.source_glow",
    )
    glow_enabled = source_glow.get("enabled", False)
    if not isinstance(glow_enabled, bool):
        raise RecipeError("effects.source_glow.enabled must be boolean")
    _number(source_glow.get("threshold", 0.65), "effects.source_glow.threshold", 0.25, 0.95)
    _number(source_glow.get("knee", 0.10), "effects.source_glow.knee", 0.0, 0.30)
    _number(
        source_glow.get("radius_fraction", 0.015),
        "effects.source_glow.radius_fraction",
        0.001,
        0.05,
    )
    glow_strength = _number(
        source_glow.get("strength", 0.0),
        "effects.source_glow.strength",
        0.0,
        0.35,
    )
    if glow_enabled:
        if effects.get("permission") != "source-derived":
            raise RecipeError("enabled source glow requires effects.permission 'source-derived'")
        if effects.get("selection") != "explicit-user":
            raise RecipeError("enabled source glow requires explicit user consent")
        if glow_strength <= 0.0:
            raise RecipeError("enabled source glow requires positive strength")
    elif effects:
        if effects.get("permission") != "none" or effects.get("selection") != "not-required":
            raise RecipeError("disabled effects must use permission 'none' and selection 'not-required'")

    texture = _object(recipe.get("texture"), "texture")
    if "texture" in recipe and schema_version != "1.3":
        raise RecipeError("texture refinement requires schema_version '1.3'")
    _only_keys(texture, {"permission", "selection", "mode", "output_sharpen"}, "texture")
    output_sharpen = _object(texture.get("output_sharpen"), "texture.output_sharpen")
    _only_keys(
        output_sharpen,
        {"enabled", "amount", "radius_pixels", "threshold", "protect_skin", "protect_noise"},
        "texture.output_sharpen",
    )
    sharpen_enabled = output_sharpen.get("enabled", False)
    if not isinstance(sharpen_enabled, bool):
        raise RecipeError("texture.output_sharpen.enabled must be boolean")
    sharpen_amount = _number(
        output_sharpen.get("amount", 0.0),
        "texture.output_sharpen.amount",
        0.0,
        0.35,
    )
    _number(
        output_sharpen.get("radius_pixels", 0.8),
        "texture.output_sharpen.radius_pixels",
        0.5,
        1.5,
    )
    _number(
        output_sharpen.get("threshold", 0.012),
        "texture.output_sharpen.threshold",
        0.005,
        0.04,
    )
    for key in ("protect_skin", "protect_noise"):
        if not isinstance(output_sharpen.get(key, True), bool):
            raise RecipeError(f"texture.output_sharpen.{key} must be boolean")
    if sharpen_enabled:
        if texture.get("permission") != "source-derived-only":
            raise RecipeError("enabled output sharpening requires texture.permission 'source-derived-only'")
        if texture.get("selection") != "explicit-user":
            raise RecipeError("enabled output sharpening requires an explicit user request")
        if texture.get("mode") != "refine":
            raise RecipeError("enabled output sharpening requires texture.mode 'refine'")
        if sharpen_amount <= 0.0:
            raise RecipeError("enabled output sharpening requires a positive amount")
    elif texture:
        raise RecipeError("omit texture when output sharpening is disabled")

    protection = _object(recipe.get("protection"), "protection")
    _only_keys(protection, {"skin"}, "protection")
    skin = _object(protection.get("skin"), "protection.skin")
    _only_keys(skin, {"enabled", "strength"}, "protection.skin")
    if not isinstance(skin.get("enabled", False), bool):
        raise RecipeError("protection.skin.enabled must be boolean")
    _number(skin.get("strength", 0.0), "protection.skin.strength", 0.0, 1.0)

    quality_tolerances = _object(recipe.get("quality_tolerances"), "quality_tolerances")
    _only_keys(
        quality_tolerances,
        {"intentional_near_black_increase", "reason"},
        "quality_tolerances",
    )
    intentional_black = _number(
        quality_tolerances.get("intentional_near_black_increase", 0.0),
        "quality_tolerances.intentional_near_black_increase",
        0.0,
        0.25,
    )
    if intentional_black > 0.0:
        if schema_version not in {"1.2", "1.3"}:
            raise RecipeError("nonzero quality tolerances require schema_version '1.2' or '1.3'")
        if strategy.get("intensity") != "transformative":
            raise RecipeError("near-black intent tolerance is limited to transformative strategy")
        reason = quality_tolerances.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise RecipeError("nonzero quality tolerance requires a reason")

    output = _object(recipe.get("output"), "output")
    _only_keys(output, {"format", "quality", "profile", "preserve_metadata"}, "output")
    if output.get("format", "png") not in {"png", "jpeg"}:
        raise RecipeError("output.format must be png or jpeg")
    quality = output.get("quality", 95)
    if isinstance(quality, bool) or not isinstance(quality, int) or not 85 <= quality <= 100:
        raise RecipeError("output.quality must be an integer in [85, 100]")
    if output.get("profile", "sRGB") != "sRGB":
        raise RecipeError("v0.3.4 output.profile must be sRGB")
    if not isinstance(output.get("preserve_metadata", True), bool):
        raise RecipeError("output.preserve_metadata must be boolean")
    return recipe


def load_recipe(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        recipe = json.load(handle)
    return validate_recipe(recipe)


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    clipped = np.clip(rgb, 0.0, None)
    return np.where(clipped <= 0.0031308, 12.92 * clipped, 1.055 * clipped ** (1.0 / 2.4) - 0.055)


def luminance(linear_rgb: np.ndarray) -> np.ndarray:
    return np.sum(linear_rgb * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=2)


def _apply_saturation(rgb: np.ndarray, factor: float) -> np.ndarray:
    if math.isclose(factor, 1.0):
        return rgb
    luma = luminance(rgb)[..., None]
    return luma + (rgb - luma) * factor


def _apply_vibrance(rgb: np.ndarray, amount: float) -> np.ndarray:
    if math.isclose(amount, 0.0):
        return rgb
    maximum = np.max(np.clip(rgb, 0.0, None), axis=2)
    minimum = np.min(np.clip(rgb, 0.0, None), axis=2)
    saturation = np.zeros_like(maximum)
    np.divide(maximum - minimum, maximum, out=saturation, where=maximum > 1e-8)
    factor = np.clip(1.0 + amount * (1.0 - np.clip(saturation, 0.0, 1.0)), 0.0, 3.0)
    luma = luminance(rgb)[..., None]
    return luma + (rgb - luma) * factor[..., None]


def _rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized HSV conversion for encoded sRGB values in [0, 1]."""
    clipped = np.clip(rgb, 0.0, 1.0)
    maximum = np.max(clipped, axis=2)
    minimum = np.min(clipped, axis=2)
    delta = maximum - minimum
    saturation = np.divide(delta, maximum, out=np.zeros_like(delta), where=maximum > 1e-8)
    hue = np.zeros_like(maximum)
    valid = delta > 1e-8
    red = valid & (maximum == clipped[..., 0])
    green = valid & (maximum == clipped[..., 1])
    blue = valid & (maximum == clipped[..., 2])
    hue[red] = np.mod((clipped[..., 1][red] - clipped[..., 2][red]) / delta[red], 6.0)
    hue[green] = (clipped[..., 2][green] - clipped[..., 0][green]) / delta[green] + 2.0
    hue[blue] = (clipped[..., 0][blue] - clipped[..., 1][blue]) / delta[blue] + 4.0
    return np.mod(hue / 6.0, 1.0), saturation, maximum


def _hsv_to_rgb(hue: np.ndarray, saturation: np.ndarray, value: np.ndarray) -> np.ndarray:
    hue6 = np.mod(hue, 1.0) * 6.0
    sector = np.floor(hue6).astype(np.int32)
    fraction = hue6 - np.floor(hue6)
    p = value * (1.0 - saturation)
    q = value * (1.0 - saturation * fraction)
    t = value * (1.0 - saturation * (1.0 - fraction))
    choices = (
        np.stack((value, t, p), axis=2),
        np.stack((q, value, p), axis=2),
        np.stack((p, value, t), axis=2),
        np.stack((p, q, value), axis=2),
        np.stack((t, p, value), axis=2),
        np.stack((value, p, q), axis=2),
    )
    return np.choose(np.mod(sector, 6)[..., None], choices)


def _soft_range_gate(values: np.ndarray, bounds: list[float], feather: float) -> np.ndarray:
    low, high = [float(item) for item in bounds]
    if feather <= 0.0:
        return ((values >= low) & (values <= high)).astype(np.float32)
    left = np.clip((values - (low - feather)) / feather, 0.0, 1.0)
    right = np.clip(((high + feather) - values) / feather, 0.0, 1.0)
    return np.minimum(left, right)


def _apply_hue_ranges(rgb: np.ndarray, ranges: list[dict[str, Any]]) -> np.ndarray:
    """Apply order-independent remaps selected from one immutable source-color state."""
    if not ranges:
        return rgb

    source = rgb
    encoded = np.clip(linear_to_srgb(source), 0.0, 1.0)
    hue, saturation, value = _rgb_to_hsv(encoded)
    source_luma = np.clip(luminance(source), 0.0, 1.0)
    weighted_candidates = np.zeros_like(source)
    weight_sum = np.zeros(source.shape[:2], dtype=np.float32)
    remaining = np.ones(source.shape[:2], dtype=np.float32)
    for item in ranges:
        center = float(item["center_degrees"]) / 360.0
        half_width = float(item["width_degrees"]) / 720.0
        feather_hue = float(item.get("feather_degrees", 0.0)) / 360.0
        distance = np.abs(np.mod(hue - center + 0.5, 1.0) - 0.5)
        if feather_hue <= 0.0:
            hue_gate = (distance <= half_width).astype(np.float32)
        else:
            hue_gate = np.clip((half_width + feather_hue - distance) / feather_hue, 0.0, 1.0)
        range_feather = float(item.get("range_feather", 0.05))
        saturation_gate = _soft_range_gate(
            saturation, item.get("saturation_range", [0.0, 1.0]), range_feather
        )
        luminance_gate = _soft_range_gate(
            source_luma, item.get("luminance_range", [0.0, 1.0]), range_feather
        )
        weight = (
            hue_gate * saturation_gate * luminance_gate * float(item.get("strength", 1.0))
        )
        shifted_hue = np.mod(hue + float(item.get("hue_shift_degrees", 0.0)) / 360.0, 1.0)
        shifted_saturation = np.clip(
            saturation * float(item.get("saturation_scale", 1.0)), 0.0, 1.0
        )
        shifted_encoded = _hsv_to_rgb(shifted_hue, shifted_saturation, value)
        shifted_linear = srgb_to_linear(shifted_encoded)
        shifted_luma = np.maximum(luminance(shifted_linear), 1e-8)
        target_luma = source_luma * float(item.get("luminance_scale", 1.0))
        shifted_linear *= (target_luma / shifted_luma)[..., None]
        weighted_candidates += shifted_linear * weight[..., None]
        weight_sum += weight
        remaining *= 1.0 - np.clip(weight, 0.0, 1.0)

    mixed = np.divide(
        weighted_candidates,
        weight_sum[..., None],
        out=source.copy(),
        where=weight_sum[..., None] > 1e-8,
    )
    blend = np.clip(1.0 - remaining, 0.0, 1.0)
    return source * (1.0 - blend[..., None]) + mixed * blend[..., None]


def _compress_chroma_to_unit_gamut(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    luma = np.clip(luminance(rgb), 0.0, 1.0)
    chroma = rgb - luma[..., None]
    limits = np.ones_like(rgb, dtype=np.float32)
    positive = chroma > 1e-8
    negative = chroma < -1e-8
    safe_encoded_max = 253.0 / 255.0
    safe_linear_max = ((safe_encoded_max + 0.055) / 1.055) ** 2.4
    np.divide((safe_linear_max - luma)[..., None], chroma, out=limits, where=positive)
    negative_limits = np.ones_like(rgb, dtype=np.float32)
    np.divide(luma[..., None], -chroma, out=negative_limits, where=negative)
    limits = np.where(negative, negative_limits, limits)
    scale = np.clip(np.min(limits, axis=2), 0.0, 1.0)
    compressed = luma[..., None] + chroma * scale[..., None]
    return compressed, float(np.mean(scale < 0.9999))


def _skin_mask(encoded_rgb: np.ndarray) -> np.ndarray:
    r, g, b = [encoded_rgb[..., index] * 255.0 for index in range(3)]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = 128.0 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128.0 + 0.5 * r - 0.418688 * g - 0.081312 * b

    def soft_range(values: np.ndarray, low: float, high: float, feather: float) -> np.ndarray:
        left = np.clip((values - (low - feather)) / feather, 0.0, 1.0)
        right = np.clip(((high + feather) - values) / feather, 0.0, 1.0)
        return np.minimum(left, right)

    confidence = soft_range(cb, 77.0, 127.0, 12.0) * soft_range(cr, 133.0, 173.0, 12.0)
    confidence *= np.clip((y - 25.0) / 35.0, 0.0, 1.0)
    confidence *= np.clip((r - b + 15.0) / 45.0, 0.0, 1.0)
    mask_image = Image.fromarray(np.uint8(np.clip(confidence, 0.0, 1.0) * 255), mode="L")
    radius = max(1.0, min(encoded_rgb.shape[:2]) * 0.002)
    return np.asarray(mask_image.filter(ImageFilter.GaussianBlur(radius=radius)), dtype=np.float32) / 255.0


def _apply_correction(rgb: np.ndarray, correction: dict[str, Any]) -> np.ndarray:
    result = rgb * (2.0 ** float(correction.get("exposure_ev", 0.0)))
    gains = np.asarray(correction.get("white_balance", {}).get("rgb_gains", [1.0, 1.0, 1.0]), dtype=np.float32)
    gains /= float(np.prod(gains) ** (1.0 / 3.0))
    result = result * gains
    black = float(correction.get("black_point", 0.0))
    white = float(correction.get("white_point", 1.0))
    source_luma = np.maximum(luminance(result), 0.0)
    mapped_luma = np.clip((source_luma - black) / (white - black), 0.0, None)
    rolloff = float(correction.get("highlight_rolloff", 0.0))
    if rolloff:
        threshold = 0.55
        normalized = np.clip((mapped_luma - threshold) / (1.0 - threshold), 0.0, None)
        shaped = normalized / (1.0 + rolloff * normalized)
        mapped_luma = np.where(
            mapped_luma > threshold,
            threshold + (1.0 - threshold) * shaped,
            mapped_luma,
        )
    # Scale all channels together so black/white mapping and highlight rolloff
    # change luminance without introducing colored channel clipping.
    scale = np.divide(mapped_luma, source_luma, out=np.zeros_like(mapped_luma), where=source_luma > 1e-8)
    result = result * scale[..., None]
    return result


def _apply_look(rgb: np.ndarray, look: dict[str, Any]) -> np.ndarray:
    result = rgb.copy()
    curve_strength = float(look.get("tone_curve", {}).get("strength", 0.0))
    if curve_strength > 0:
        clipped = np.clip(result, 0.0, 1.0)
        smooth = clipped * clipped * (3.0 - 2.0 * clipped)
        result = result * (1.0 - curve_strength) + smooth * curve_strength
    elif curve_strength < 0:
        amount = -curve_strength
        clipped = np.clip(result, 0.0, 1.0)
        centered = 2.0 * clipped - 1.0
        softened = 0.5 + 0.5 * centered * np.abs(centered)
        result = result * (1.0 - amount) + softened * amount

    cdl = look.get("cdl", {})
    slope = np.asarray(cdl.get("slope", [1.0, 1.0, 1.0]), dtype=np.float32)
    offset = np.asarray(cdl.get("offset", [0.0, 0.0, 0.0]), dtype=np.float32)
    power = np.asarray(cdl.get("power", [1.0, 1.0, 1.0]), dtype=np.float32)
    result = np.maximum(result * slope + offset, 0.0) ** power
    # Select hue ranges before global chroma controls so an intentionally
    # excluded saturated color cannot become eligible merely because the
    # recipe later desaturates the whole image.
    result = _apply_hue_ranges(result, look.get("hue_ranges", []))
    result = _apply_saturation(result, float(cdl.get("saturation", 1.0)))
    result = _apply_saturation(result, float(look.get("saturation", 1.0)))
    result = _apply_vibrance(result, float(look.get("vibrance", 0.0)))

    split = look.get("split_tone", {})
    split_strength = float(split.get("strength", 0.0))
    if split_strength:
        luma = np.clip(luminance(result), 0.0, 1.0)
        balance = float(split.get("balance", 0.0))
        pivot = 0.5 + 0.25 * balance
        shadow_weight = np.clip((pivot - luma) / max(pivot, 1e-6), 0.0, 1.0) ** 2
        highlight_weight = np.clip((luma - pivot) / max(1.0 - pivot, 1e-6), 0.0, 1.0) ** 2
        shadow_color = srgb_to_linear(np.asarray(split.get("shadows", [0.5, 0.5, 0.5]), dtype=np.float32))
        highlight_color = srgb_to_linear(np.asarray(split.get("highlights", [0.5, 0.5, 0.5]), dtype=np.float32))
        weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        shadow_chroma = shadow_color - float(np.dot(shadow_color, weights))
        highlight_chroma = highlight_color - float(np.dot(highlight_color, weights))
        # Fade chroma to zero near numeric black and white. Adding color to an
        # almost-black pixel creates saturated artifacts even at low strength.
        gamut_gate = np.clip(luma / 0.08, 0.0, 1.0) * np.clip((1.0 - luma) / 0.08, 0.0, 1.0)
        result += split_strength * gamut_gate[..., None] * shadow_weight[..., None] * shadow_chroma
        result += split_strength * gamut_gate[..., None] * highlight_weight[..., None] * highlight_chroma
    return result


def _blur_float_channel(channel: np.ndarray, radius: float) -> np.ndarray:
    image = Image.fromarray(np.uint8(np.round(np.clip(channel, 0.0, 1.0) * 255.0)), mode="L")
    blurred = image.filter(ImageFilter.GaussianBlur(radius=radius))
    return np.asarray(blurred, dtype=np.float32) / 255.0


def _apply_source_glow(
    base: np.ndarray,
    source_linear: np.ndarray,
    options: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    if not options.get("enabled", False):
        return base, {"enabled": False}
    threshold = float(options.get("threshold", 0.65))
    knee = float(options.get("knee", 0.10))
    radius_fraction = float(options.get("radius_fraction", 0.015))
    strength = float(options.get("strength", 0.0))
    source_luma = np.clip(luminance(source_linear), 0.0, 1.0)
    if knee > 0.0:
        lower = threshold - knee
        weight = np.clip((source_luma - lower) / (2.0 * knee), 0.0, 1.0)
        weight = weight * weight * (3.0 - 2.0 * weight)
    else:
        weight = (source_luma >= threshold).astype(np.float32)
    light = np.clip(base, 0.0, 1.0) * weight[..., None]
    radius = max(0.5, min(base.shape[:2]) * radius_fraction)
    blurred = np.stack(
        [_blur_float_channel(light[..., index], radius) for index in range(3)],
        axis=2,
    )
    glow = np.clip(blurred * strength, 0.0, 1.0)
    result = base + glow * (1.0 - np.clip(base, 0.0, 1.0))
    diagnostics = {
        "enabled": True,
        "source_highlight_fraction": round(float(np.mean(weight > 0.01)), 6),
        "radius_pixels": round(float(radius), 3),
        "strength": strength,
        "peak_added_light": round(float(np.max(glow)), 6),
    }
    return result, diagnostics


def _apply_output_sharpen(
    encoded: np.ndarray,
    source_encoded: np.ndarray,
    options: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply bounded, source-derived output sharpening without inventing detail."""
    if not options.get("enabled", False):
        return encoded, {"enabled": False}
    amount = float(options.get("amount", 0.0))
    radius = float(options.get("radius_pixels", 0.8))
    threshold = float(options.get("threshold", 0.012))
    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    luma = np.sum(np.clip(encoded, 0.0, 1.0) * weights, axis=2)
    source_luma = np.sum(np.clip(source_encoded, 0.0, 1.0) * weights, axis=2)
    blurred = _blur_float_channel(luma, radius)
    detail = luma - blurred
    magnitude = np.abs(detail)
    gate = np.clip((magnitude - threshold) / max(threshold + 0.01, 1e-6), 0.0, 1.0)
    gate = gate * gate * (3.0 - 2.0 * gate)
    if options.get("protect_noise", True):
        # Dark encoded regions and isolated sub-threshold fluctuations are the
        # most likely places for noise or JPEG artifacts to be exaggerated.
        dark_gate = 0.15 + 0.85 * np.clip((source_luma - 0.04) / 0.24, 0.0, 1.0)
        gate *= dark_gate
    if options.get("protect_skin", True):
        gate *= 1.0 - 0.85 * _skin_mask(source_encoded)
    delta = np.clip(amount * detail * gate, -0.035, 0.035)
    result = np.clip(encoded + delta[..., None], 0.0, 1.0)
    source_gradient = np.hypot(*np.gradient(luma))
    result_luma = np.sum(result * weights, axis=2)
    result_gradient = np.hypot(*np.gradient(result_luma))
    diagnostics = {
        "enabled": True,
        "mode": "refine",
        "amount": amount,
        "radius_pixels": radius,
        "threshold": threshold,
        "protect_skin": bool(options.get("protect_skin", True)),
        "protect_noise": bool(options.get("protect_noise", True)),
        "applied_fraction": round(float(np.mean(np.abs(delta) >= (0.5 / 255.0))), 6),
        "maximum_luma_delta": round(float(np.max(np.abs(delta))), 6),
        "gradient_energy_ratio": round(
            float(np.mean(result_gradient) / max(float(np.mean(source_gradient)), 1e-8)),
            6,
        ),
    }
    return result, diagnostics


def _raw_source_size(raw: Any) -> tuple[int, int] | None:
    sizes = getattr(raw, "sizes", None)
    if sizes is None:
        return None
    width = int(getattr(sizes, "width", 0) or getattr(sizes, "iwidth", 0) or 0)
    height = int(getattr(sizes, "height", 0) or getattr(sizes, "iheight", 0) or 0)
    if width <= 0 or height <= 0:
        return None
    if int(getattr(sizes, "flip", 0) or 0) in {5, 6}:
        width, height = height, width
    return width, height


def _finite_float_list(value: Any) -> list[float] | None:
    if value is None:
        return None
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    return result if result and all(math.isfinite(item) for item in result) else None


def _classify_raw_white_balance(value: Any) -> tuple[list[float] | None, str]:
    coefficients = _finite_float_list(value)
    if coefficients is None:
        return None, "missing"
    if len(coefficients) < 3 or any(item <= 0.0 for item in coefficients[:3]):
        return coefficients, "invalid"
    first_three = coefficients[:3]
    if max(first_three) / min(first_three) <= 1.01:
        return coefficients, "identity_suspect"
    return coefficients, "valid"


def _rawpy_user_white_balance(coefficients: list[float]) -> list[float]:
    """Return four positive coefficients in the layout expected by rawpy."""
    result = list(coefficients[:4])
    while len(result) < 4:
        result.append(result[1])
    if result[3] <= 0.0:
        result[3] = result[1]
    return result


def _load_raw_image(path: Path, max_size: int | None) -> tuple[np.ndarray, None, dict[str, Any]]:
    try:
        import rawpy  # type: ignore[import-not-found]
    except ImportError as error:
        raise RecipeError(
            "RAW input requires the optional rawpy/LibRaw backend; "
            "install requirements-raw.txt and retry"
        ) from error

    try:
        with rawpy.imread(str(path)) as raw:
            source_size = _raw_source_size(raw)
            orientation_flip = int(getattr(getattr(raw, "sizes", None), "flip", 0) or 0)
            half_size = bool(
                max_size
                and source_size
                and max(source_size) > int(max_size) * 2
            )
            output_bps = 8 if max_size is not None else 16
            camera_whitebalance, camera_wb_status = _classify_raw_white_balance(
                getattr(raw, "camera_whitebalance", None)
            )
            daylight_whitebalance, daylight_wb_status = _classify_raw_white_balance(
                getattr(raw, "daylight_whitebalance", None)
            )
            if camera_wb_status == "valid":
                use_camera_wb = True
                user_wb = None
                white_balance_source = "camera"
                white_balance_fallback_reason = None
            elif daylight_wb_status == "valid":
                use_camera_wb = False
                user_wb = _rawpy_user_white_balance(daylight_whitebalance)
                white_balance_source = "daylight"
                white_balance_fallback_reason = f"camera_white_balance_{camera_wb_status}"
            else:
                use_camera_wb = False
                user_wb = None
                white_balance_source = "decoder_default"
                white_balance_fallback_reason = (
                    f"camera_white_balance_{camera_wb_status};"
                    f"daylight_white_balance_{daylight_wb_status}"
                )
            decoded = raw.postprocess(
                demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
                use_camera_wb=use_camera_wb,
                use_auto_wb=False,
                user_wb=user_wb,
                no_auto_bright=True,
                output_color=rawpy.ColorSpace.sRGB,
                output_bps=output_bps,
                gamma=(2.4, 12.92),
                half_size=half_size,
                highlight_mode=rawpy.HighlightMode.Clip,
                four_color_rgb=False,
                dcb_iterations=0,
                dcb_enhance=False,
                fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Off,
                noise_thr=None,
                median_filter_passes=0,
                chromatic_aberration=None,
                bad_pixels_path=None,
            )
    except Exception as error:
        raw_error = getattr(rawpy, "LibRawError", None)
        if isinstance(error, OSError) or (raw_error is not None and isinstance(error, raw_error)):
            raise RecipeError(f"RAW decode failed or camera format is unsupported: {error}") from error
        raise

    supported_dtypes = {np.dtype("uint8"), np.dtype("uint16")}
    if decoded.ndim != 3 or decoded.shape[2] != 3 or decoded.dtype not in supported_dtypes:
        raise RecipeError("RAW backend returned an unsupported RGB array")
    if source_size is None:
        multiplier = 2 if half_size else 1
        source_size = (int(decoded.shape[1]) * multiplier, int(decoded.shape[0]) * multiplier)
    if max_size and max(decoded.shape[:2]) > max_size:
        preview_array = decoded if decoded.dtype == np.uint8 else np.uint8(decoded / 257)
        preview = Image.fromarray(preview_array, mode="RGB")
        preview.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        decoded = np.asarray(preview, dtype=np.uint8)
        output_bps = 8
    scale = 65535.0 if decoded.dtype == np.uint16 else 255.0
    array = decoded.astype(np.float32) / scale
    rawpy_version = str(getattr(rawpy, "__version__", "unknown"))
    libraw_version = getattr(rawpy, "libraw_version", "unknown")
    if isinstance(libraw_version, tuple):
        libraw_version = ".".join(str(part) for part in libraw_version)
    camera_wb_valid = camera_wb_status == "valid"
    daylight_wb_valid = daylight_wb_status == "valid"
    warnings = [
        "RAW was deterministically demosaiced with no automatic white balance or automatic brightening",
        "maker-specific EXIF and edit instructions are not copied; the sidecar records development provenance instead",
    ]
    if white_balance_source == "daylight":
        warnings.append(
            "camera white balance was unavailable or suspect; deterministic daylight coefficients were used"
        )
    elif white_balance_source == "decoder_default":
        warnings.append(
            "camera and daylight white balance were unavailable or invalid; decoder defaults were used, so review neutral colors"
        )
    development = {
        "backend": "rawpy/LibRaw",
        "rawpy_version": rawpy_version,
        "libraw_version": str(libraw_version),
        "camera_white_balance_requested": use_camera_wb,
        "camera_white_balance": camera_whitebalance,
        "camera_white_balance_valid": camera_wb_valid,
        "camera_white_balance_status": camera_wb_status,
        "daylight_white_balance": daylight_whitebalance,
        "daylight_white_balance_valid": daylight_wb_valid,
        "daylight_white_balance_status": daylight_wb_status,
        "white_balance_source": white_balance_source,
        "white_balance_fallback_reason": white_balance_fallback_reason,
        "auto_white_balance": False,
        "auto_brightness": False,
        "output_color": "sRGB",
        "output_bps": output_bps,
        "graded_derivative_bps": 8,
        "gamma": [2.4, 12.92],
        "half_size": half_size,
        "orientation_flip": orientation_flip,
        "demosaic_algorithm": "AHD",
        "highlight_mode": "clip",
        "detail_operations": {
            "four_color_rgb": False,
            "dcb_iterations": 0,
            "dcb_enhance": False,
            "fbdd_noise_reduction": "off",
            "noise_threshold": None,
            "median_filter_passes": 0,
            "chromatic_aberration_correction": False,
            "bad_pixel_map": False,
            "sharpening": False,
        },
    }
    info = {
        "source_mode": "RAW",
        "source_size": source_size,
        "source_icc_present": False,
        "working_profile": "sRGB",
        "color_management": "rawpy_libraw_camera_to_srgb",
        "warnings": warnings,
        "output_icc_profile": _srgb_profile_bytes(),
        "exif": None,
        "raw_development": development,
    }
    return array, None, info


def load_image(path: str | Path, max_size: int | None = None) -> tuple[np.ndarray, np.ndarray | None, dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() in RAW_EXTENSIONS:
        return _load_raw_image(path, max_size)
    with Image.open(path) as source:
        if source.format not in {"JPEG", "PNG"}:
            raise RecipeError("v0.3.4 accepts only JPEG and PNG images")
        if getattr(source, "n_frames", 1) != 1:
            raise RecipeError("v0.3.4 accepts only single-frame images")
        if source.mode in {"I", "I;16", "I;16B", "I;16L", "F"}:
            raise RecipeError("v0.3.4 accepts only 8-bit image channels")
        embedded_profile = source.info.get("icc_profile")
        info = {
            "source_mode": source.mode,
            "source_size": source.size,
            "source_icc_present": embedded_profile is not None,
            "working_profile": "sRGB",
            "color_management": "assumed_srgb",
            "warnings": [],
            "output_icc_profile": _srgb_profile_bytes(),
            "exif": source.getexif().tobytes() if source.getexif() else None,
        }
        has_alpha = source.mode in {"RGBA", "LA"} or "transparency" in source.info
        alpha_image = source.convert("RGBA").getchannel("A") if has_alpha else None
        image = source.convert("RGB")
        if embedded_profile:
            try:
                profile_source = source.copy() if source.mode in {"RGB", "CMYK", "LAB", "L"} else image
                image = ImageCms.profileToProfile(
                    profile_source,
                    ImageCms.ImageCmsProfile(io.BytesIO(embedded_profile)),
                    ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")),
                    outputMode="RGB",
                )
                info["color_management"] = "converted_embedded_icc_to_srgb"
            except (ImageCms.PyCMSError, OSError, TypeError, ValueError) as error:
                info["color_management"] = "invalid_icc_assumed_srgb"
                info["warnings"].append(f"embedded ICC profile could not be decoded; assumed sRGB: {error}")
        elif source.mode == "CMYK":
            info["color_management"] = "untagged_cmyk_converted_to_rgb"
            info["warnings"].append("untagged CMYK JPEG was converted with Pillow defaults; color interpretation is uncertain")
        if max_size and max(image.size) > max_size:
            image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            if alpha_image is not None:
                alpha_image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        array = np.asarray(image, dtype=np.float32) / 255.0
        alpha = None
        if alpha_image is not None:
            alpha = np.asarray(alpha_image, dtype=np.float32)[..., None] / 255.0
    return array, alpha, info


def render_array(encoded_rgb: np.ndarray, recipe: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    validate_recipe(recipe)
    original_linear = srgb_to_linear(encoded_rgb)
    corrected = _apply_correction(original_linear, recipe.get("correction", {}))
    looked = _apply_look(corrected, recipe.get("look", {}))
    skin_options = recipe.get("protection", {}).get("skin", {})
    skin_fraction = 0.0
    protection_amount = None
    if skin_options.get("enabled", False) and float(skin_options.get("strength", 0.0)) > 0:
        mask = _skin_mask(encoded_rgb)
        skin_fraction = float(np.mean(mask > 0.5))
        amount = mask[..., None] * float(skin_options["strength"])
        looked = looked * (1.0 - amount) + corrected * amount
        protection_amount = amount
    glow_options = recipe.get("effects", {}).get("source_glow", {})
    pre_glow = looked
    looked, glow_diagnostics = _apply_source_glow(looked, original_linear, glow_options)
    if protection_amount is not None and glow_diagnostics.get("enabled", False):
        looked = looked * (1.0 - protection_amount) + pre_glow * protection_amount
    if not np.all(np.isfinite(looked)):
        raise RuntimeError("render produced non-finite pixels")
    looked, gamut_compressed_fraction = _compress_chroma_to_unit_gamut(looked)
    encoded = np.clip(linear_to_srgb(looked), 0.0, 1.0)
    texture_options = recipe.get("texture", {}).get("output_sharpen", {})
    encoded, texture_diagnostics = _apply_output_sharpen(
        encoded,
        encoded_rgb,
        texture_options,
    )
    return encoded, {
        "skin_fraction": skin_fraction,
        "source_glow": glow_diagnostics,
        "texture": texture_diagnostics,
        "gamut_compressed_fraction": round(gamut_compressed_fraction, 6),
    }


def save_image(
    path: str | Path,
    encoded_rgb: np.ndarray,
    alpha: np.ndarray | None,
    recipe: dict[str, Any],
    metadata: dict[str, Any],
    *,
    png_compress_level: int = 6,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output_options = recipe.get("output", {})
    expected = output_options.get("format", "png")
    suffix = output.suffix.lower()
    if expected == "png" and suffix != ".png":
        raise RecipeError("PNG recipe requires a .png output path")
    if expected == "jpeg" and suffix not in {".jpg", ".jpeg"}:
        raise RecipeError("JPEG recipe requires a .jpg or .jpeg output path")
    rgb8 = np.uint8(np.round(np.clip(encoded_rgb, 0.0, 1.0) * 255.0))
    if alpha is not None:
        alpha8 = np.uint8(np.round(np.clip(alpha, 0.0, 1.0) * 255.0))
        array = np.concatenate([rgb8, alpha8], axis=2)
        image = Image.fromarray(array, mode="RGBA")
    else:
        image = Image.fromarray(rgb8, mode="RGB")
    save_args: dict[str, Any] = {}
    # Pixel values are always encoded as sRGB, so the output profile must be
    # sRGB too. Reattaching a non-sRGB source profile would reinterpret them.
    save_args["icc_profile"] = metadata.get("output_icc_profile") or _srgb_profile_bytes()
    if output_options.get("preserve_metadata", True):
        if metadata.get("exif"):
            save_args["exif"] = metadata["exif"]
    if expected == "jpeg":
        if image.mode == "RGBA":
            raise RecipeError("JPEG output cannot preserve alpha; choose PNG")
        save_args.update(quality=int(output_options.get("quality", 95)), subsampling=0, optimize=True)
        image.save(output, format="JPEG", **save_args)
    else:
        if not 0 <= png_compress_level <= 9:
            raise ValueError("png_compress_level must be in [0, 9]")
        image.save(output, format="PNG", compress_level=png_compress_level, **save_args)


def analyze_array(encoded_rgb: np.ndarray) -> dict[str, Any]:
    linear = srgb_to_linear(encoded_rgb)
    luma = luminance(linear)
    maximum = np.max(encoded_rgb, axis=2)
    minimum = np.min(encoded_rgb, axis=2)
    saturation = np.zeros_like(maximum)
    np.divide(maximum - minimum, maximum, out=saturation, where=maximum > 1e-6)
    skin = _skin_mask(encoded_rgb)
    luma_percentiles = {
        str(percentile): round(float(np.percentile(luma, percentile)), 6)
        for percentile in (1, 5, 25, 50, 75, 95, 99)
    }
    low = float(luma_percentiles["25"])
    high = float(luma_percentiles["75"])

    def zone_mean(mask: np.ndarray) -> list[float]:
        values = encoded_rgb[mask]
        if values.size == 0:
            values = encoded_rgb.reshape(-1, 3)
        return [round(float(value), 6) for value in np.mean(values, axis=0)]

    return {
        "channel_mean_srgb": [round(float(value), 6) for value in np.mean(encoded_rgb, axis=(0, 1))],
        "luminance_percentiles_linear": luma_percentiles,
        "tonal_zone_mean_srgb": {
            "shadows": zone_mean(luma <= low),
            "midtones": zone_mean((luma > low) & (luma < high)),
            "highlights": zone_mean(luma >= high),
        },
        "clipping": {
            "near_black_fraction": round(float(np.mean(luma <= 1.0 / 255.0)), 6),
            "near_white_fraction": round(float(np.mean(luma >= 254.0 / 255.0)), 6),
            "any_channel_high_fraction": round(float(np.mean(np.any(encoded_rgb >= 254.0 / 255.0, axis=2))), 6),
        },
        "saturation": {
            "p25": round(float(np.percentile(saturation, 25)), 6),
            "median": round(float(np.median(saturation)), 6),
            "p75": round(float(np.percentile(saturation, 75)), 6),
            "p95": round(float(np.percentile(saturation, 95)), 6),
            "extreme_fraction": round(float(np.mean(saturation >= 0.98)), 6),
        },
        "skin_candidate_fraction": round(float(np.mean(skin > 0.5)), 6),
    }
