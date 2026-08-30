# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np
from PIL import Image

from grade_core import _skin_mask, analyze_array


def _component_stats(mask: np.ndarray) -> tuple[int, float]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components = 0
    largest = 0
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue
            components += 1
            size = 0
            queue = deque([(y, x)])
            visited[y, x] = True
            while queue:
                cy, cx = queue.popleft()
                size += 1
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((ny, nx))
            largest = max(largest, size)
    candidates = int(np.count_nonzero(mask))
    return components, (largest / candidates if candidates else 0.0)


def scene_evidence(encoded_rgb: np.ndarray) -> dict[str, Any]:
    confidence = _skin_mask(encoded_rgb)
    binary = confidence > 0.5
    height, width = binary.shape
    reduced = Image.fromarray(np.uint8(binary) * 255, mode="L")
    reduced.thumbnail((128, 128), Image.Resampling.NEAREST)
    small = np.asarray(reduced, dtype=np.uint8) > 0
    component_count, largest_component_fraction = _component_stats(small)
    border = np.concatenate((small[0], small[-1], small[:, 0], small[:, -1]))
    border_candidate_fraction = float(np.mean(border)) if border.size else 0.0
    y0, y1 = int(height * 0.2), max(int(height * 0.8), 1)
    x0, x1 = int(width * 0.2), max(int(width * 0.8), 1)
    central = binary[y0:y1, x0:x1]
    central_candidate_fraction = float(np.mean(central)) if central.size else 0.0
    coverage = float(np.mean(binary))
    warnings = []
    if coverage > 0.35:
        warnings.append("skin-color candidates cover more than 35%; warm materials or lighting are likely")
    if coverage > 0.10 and largest_component_fraction > 0.80 and border_candidate_fraction > 0.20:
        warnings.append("skin-color candidates form one broad border-touching region rather than compact subjects")
    return {
        "schema_version": "1.0",
        "skin_color_candidate": {
            "coverage_fraction": round(coverage, 6),
            "central_fraction": round(central_candidate_fraction, 6),
            "border_fraction": round(border_candidate_fraction, 6),
            "component_count_128px": component_count,
            "largest_component_fraction": round(largest_component_fraction, 6),
            "semantic_claim": "none; color-and-space evidence only",
        },
        "warnings": warnings,
    }


def skin_protection_gate(evidence: dict[str, Any], people_evidence: str = "unknown") -> dict[str, Any]:
    if people_evidence not in {"present", "absent", "unknown"}:
        raise ValueError("people_evidence must be present, absent, or unknown")
    candidate = evidence["skin_color_candidate"]
    coverage = float(candidate["coverage_fraction"])
    broad_warm_region = coverage > 0.35 or (
        coverage > 0.10
        and float(candidate["largest_component_fraction"]) > 0.80
        and float(candidate["border_fraction"]) > 0.20
    )
    if people_evidence == "absent":
        decision, reason = "disable", "visual evidence says no people are present"
    elif coverage < 0.001:
        decision, reason = "disable", "no reliable skin-color candidate was measured"
    elif broad_warm_region:
        decision, reason = "disable", "candidate coverage is broad and consistent with warm scene materials"
    elif people_evidence == "present":
        decision, reason = "enable", "people evidence is present and the candidate mask is spatially bounded"
    else:
        decision, reason = "review", "color evidence alone cannot establish that a person is present"
    return {
        "people_evidence": people_evidence,
        "decision": decision,
        "recommended_enabled": decision == "enable",
        "reason": reason,
    }


def build_intent_record(prompt: str, measurements: dict[str, Any], evidence: dict[str, Any], people_evidence: str) -> dict[str, Any]:
    normalized = prompt.casefold()
    intensity_terms = {
        "transformative": ("transformative", "变革型", "彻底改变", "大幅改变"),
        "bold": ("bold", "dramatic", "大胆", "强烈", "浓郁", "明显"),
        "conservative": ("conservative", "subtle", "保守", "轻微", "微调", "克制"),
    }
    intensity = "standard"
    intensity_source = "default-standard"
    for value, terms in intensity_terms.items():
        if any(term in normalized for term in terms):
            intensity, intensity_source = value, "explicit-prompt"
            break
    style_terms = {
        "cinematic": ("cinematic", "电影感"),
        "natural": ("natural", "自然"),
        "film": ("film", "胶片", "analog"),
        "documentary": ("documentary", "纪实"),
    }
    styles = [name for name, terms in style_terms.items() if any(term in normalized for term in terms)]
    effect_cues = [term for term in ("glow", "dreamy", "柔光", "梦幻", "辉光", "光晕") if term in normalized]
    gate = skin_protection_gate(evidence, people_evidence)
    return {
        "schema_version": "1.0",
        "prompt": prompt,
        "intent": {
            "intensity": {"value": intensity, "source": intensity_source},
            "styles": {"value": styles or ["custom"], "source": "explicit-prompt" if styles else "unresolved"},
            "effects": {
                "cues": effect_cues,
                "permission": False,
                "source": "not-explicitly-approved",
            },
            "texture": {"permission": False, "source": "not-explicitly-requested"},
        },
        "source_facts": {
            "near_black_fraction": measurements["clipping"]["near_black_fraction"],
            "near_white_fraction": measurements["clipping"]["near_white_fraction"],
            "saturation_p95": measurements["saturation"]["p95"],
        },
        "scene_evidence": evidence,
        "routing": {"skin_protection": gate},
    }

