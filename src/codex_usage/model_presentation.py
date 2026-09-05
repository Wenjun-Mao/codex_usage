from __future__ import annotations

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
}


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
    """Keep known model colors stable and allocate remaining chart slots deterministically."""
    assigned: dict[str, int] = {}
    used: set[int] = set()

    for model in models:
        preferred = _STABLE_COLOR_SLOTS.get(model.casefold())
        if preferred is not None and preferred not in used:
            assigned[model] = preferred
            used.add(preferred)

    remaining_slots = (slot for slot in range(7) if slot not in used)
    for model in models:
        if model not in assigned:
            assigned[model] = next(remaining_slots)
    return assigned
