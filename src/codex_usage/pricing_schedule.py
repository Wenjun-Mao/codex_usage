"""Bounded identity cache for immutable effective-dated pricing schedules."""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

from codex_usage.models import TokenUsage
from codex_usage.pricing_models import ModelRate, RequestPricingContract, STANDARD_REQUEST_PRICING


@dataclass(frozen=True)
class EffectiveModelRate:
    model_key: str
    effective_from: datetime
    rate: ModelRate
    aliases: tuple[str, ...] = ()
    request_pricing_contract: RequestPricingContract = STANDARD_REQUEST_PRICING

    def rate_for_usage(self, usage: TokenUsage) -> ModelRate:
        return self.request_pricing_contract.rate_for_usage(self.rate, usage)


@dataclass(frozen=True, slots=True)
class _EffectiveRateTimeline:
    effective_from: tuple[datetime, ...]
    entries: tuple[EffectiveModelRate, ...]


@dataclass(frozen=True, slots=True, eq=False)
class _ScheduleKey:
    schedule: tuple[EffectiveModelRate, ...]

    def __hash__(self):
        return id(self.schedule)

    def __eq__(self, other):
        return isinstance(other, _ScheduleKey) and self.schedule is other.schedule


def schedule_entry_for_model(schedule, model, at=None):
    timeline = _compiled_schedule(_ScheduleKey(schedule)).get(model.strip().casefold())
    if timeline is None:
        return None
    effective_at = normalize_effective_at(at)
    if effective_at is None:
        return timeline.entries[-1]
    index = bisect_right(timeline.effective_from, effective_at) - 1
    return None if index < 0 else timeline.entries[index]


@lru_cache(maxsize=8)
def _compiled_schedule(key):
    # Hold the immutable tuple in the key: object IDs cannot be recycled while
    # cached, and replacing a schedule never reuses its compiled predecessors.
    indexed = {}
    for entry in key.schedule:
        keys = {entry.model_key.strip().casefold()}
        keys.update(alias.strip().casefold() for alias in entry.aliases)
        for name in keys:
            indexed.setdefault(name, []).append(entry)
    compiled = {}
    for name, entries in indexed.items():
        ordered = tuple(sorted(entries, key=lambda entry: normalize_effective_at(entry.effective_from)))
        compiled[name] = _EffectiveRateTimeline(
            tuple(normalize_effective_at(entry.effective_from) for entry in ordered), ordered)
    return compiled


def normalize_effective_at(value):
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
