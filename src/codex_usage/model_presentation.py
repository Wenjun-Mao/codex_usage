from __future__ import annotations

import hashlib
import re

_GPT_GENERATION = re.compile(
    r"^gpt-(?P<generation>\d+(?:\.\d+)*)(?:-(?P<tier>.*))?$",
    re.IGNORECASE,
)
_TIER_ORDER = {
    "astra": 0,
    "": 1,
    "sol": 1,
    "terra": 2,
    "luna": 3,
    "mini": 4,
}
_STABLE_COLOR_SLOTS = {
    "gpt-6-astra": 0,
    "gpt-5.6-sol": 1,
    "gpt-5.6-terra": 2,
    "gpt-5.6-luna": 3,
    "gpt-6-sol": 4,
    "gpt-6-luna": 5,
    "gpt-6.1-sol": 6,
    "gpt-6.1-terra": 8,
}
# Slot 7 belongs to neutral Other aggregates, never an individual model.
MODEL_COLOR_SLOTS = (0, 1, 2, 3, 4, 5, 6, 8)
# Cross-release contract: this fallback domain is frozen, even when the known
# registry or MODEL_COLOR_SLOTS grows. Never change its order or length.
_FALLBACK_COLOR_SLOTS = (0, 1, 2, 3, 4, 5, 6, 8)


def model_color_slot(model: str) -> int:
    """Presentation identity only; labels and accounting model keys are untouched.

    Unknown names share a finite palette (and its marker shapes). Hash collisions
    are intentional: resolving them from visible peers would change identity on
    filtering. SHA-256 is stable across processes, unlike Python's hash().
    """
    normalized = model.casefold()
    if normalized in _STABLE_COLOR_SLOTS:
        return _STABLE_COLOR_SLOTS[normalized]
    index = int.from_bytes(hashlib.sha256(normalized.encode()).digest()[:8])
    return _FALLBACK_COLOR_SLOTS[index % len(_FALLBACK_COLOR_SLOTS)]


def model_color(model: str) -> str:
    return f"var(--model-{model_color_slot(model)})"


def model_display_sort_key(model: str) -> tuple[object, ...]:
    """Order recognized GPT models by generation, then product tier."""
    normalized = model.casefold()
    match = _GPT_GENERATION.fullmatch(normalized)
    if match is None:
        return (1, normalized, model)

    generation = tuple(int(part) for part in match.group("generation").split("."))
    padded_generation = (*generation[:4], *(0 for _ in range(max(0, 4 - len(generation)))))
    tier = match.group("tier") or ""
    tier_name = tier.split("-", 1)[0]
    tier_rank = _TIER_ORDER.get(tier_name, 100)
    return (0, *(-part for part in padded_generation), tier_rank, tier, normalized, model)


def assign_model_color_slots(models: tuple[str, ...]) -> dict[str, int]:
    """Assign each name independently of visible membership and order."""
    return {model: model_color_slot(model) for model in models}
