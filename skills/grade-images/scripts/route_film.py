# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SKILL = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = SKILL / "references" / "film-color-catalog.json"


def load_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if catalog.get("schema_version") != "1.0":
        raise ValueError("film color catalog must use schema_version 1.0")
    profiles = catalog.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("film color catalog must contain profiles")
    ids: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict) or not isinstance(profile.get("id"), str):
            raise ValueError("every film color profile must contain a string id")
        profile_id = profile["id"]
        if profile_id in ids:
            raise ValueError(f"duplicate film color profile id: {profile_id}")
        ids.add(profile_id)
        recipe = (path.parent / profile.get("recipe", "")).resolve()
        if not recipe.is_file():
            raise ValueError(f"missing film color recipe for {profile_id}: {recipe}")
        if profile.get("contract", {}).get("effects") != "absent":
            raise ValueError(f"film color profile {profile_id} must keep effects absent")
    generic_ids = catalog.get("generic_route", {}).get("profiles", [])
    if not generic_ids or any(profile_id not in ids for profile_id in generic_ids):
        raise ValueError("generic film route must reference known profiles")
    return catalog


def _matches(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term.casefold() in text]


def route_prompt(prompt: str, catalog_path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    catalog = load_catalog(catalog_path)
    normalized = prompt.casefold().strip()
    effect_requests: list[dict[str, str]] = []
    for effect, terms in catalog.get("forbidden_effect_terms", {}).items():
        matched = _matches(normalized, terms)
        if matched:
            effect_requests.append(
                {
                    "effect": effect,
                    "matched_term": matched[0],
                    "status": "unsupported-under-strict-preservation",
                }
            )
    texture_requests = []
    for operation, terms in catalog.get("texture_terms", {}).items():
        matched = _matches(normalized, terms)
        if matched:
            texture_requests.append({
                "operation": operation,
                "matched_term": matched[0],
                "status": "eligible-after-source-review",
                "recipe": str((catalog_path.parent / "../assets/recipes/output-refine-standard.json").resolve()),
            })

    ranked: list[tuple[int, int, dict[str, Any], list[str], list[str]]] = []
    for index, profile in enumerate(catalog["profiles"]):
        prompt_matches = _matches(normalized, profile.get("prompt_terms", []))
        scene_matches = _matches(normalized, profile.get("scene_terms", []))
        if prompt_matches:
            score = int(profile.get("priority", 0)) + 100 * len(prompt_matches) + 5 * len(scene_matches)
            ranked.append((score, -index, profile, prompt_matches, scene_matches))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)

    generic_matches = _matches(normalized, catalog.get("generic_terms", []))
    profile_by_id = {profile["id"]: profile for profile in catalog["profiles"]}
    if ranked:
        _, _, selected, matched_terms, scene_terms = ranked[0]
        mode = "selected"
        profiles = [selected]
    elif generic_matches:
        mode = catalog["generic_route"]["mode"]
        profiles = [profile_by_id[profile_id] for profile_id in catalog["generic_route"]["profiles"]]
        matched_terms = generic_matches
        scene_terms = []
    else:
        mode = "not-applicable"
        profiles = []
        matched_terms = []
        scene_terms = []

    candidates = []
    for profile in profiles:
        recipe_path = (catalog_path.parent / profile["recipe"]).resolve()
        candidates.append(
            {
                "id": profile["id"],
                "title": profile["title"],
                "recipe": str(recipe_path),
                "contract": profile["contract"],
            }
        )
    return {
        "schema_version": "1.0",
        "mode": mode,
        "default_intensity": catalog["default_intensity"] if profiles else None,
        "matched_terms": matched_terms,
        "scene_terms": scene_terms,
        "candidates": candidates,
        "effect_requests": effect_requests,
        "texture_requests": texture_requests,
        "effect_policy": "grain, vignette, blur, light leak, distortion, clarity, dehaze, repair, denoise, and generated detail remain unsupported",
        "texture_policy": "film language stays color-only; bounded output sharpening requires a separate explicit current request, schema 1.3, and source review",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Route film-color prompts to strict color-only recipes.")
    parser.add_argument("prompt")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = route_prompt(args.prompt, args.catalog)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(args.output.resolve())
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
