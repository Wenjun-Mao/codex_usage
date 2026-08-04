from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.pricing import (
    CostBreakdown,
    CreditBreakdown,
    estimate_codex_credits,
    estimate_cost,
)

RANGE_CHOICES = ("today", "yesterday", "7d", "30d", "month", "all")
GROUP_CHOICES = ("day", "hour", "project", "model", "session")
_UTC_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class RangeBounds:
    start_us: int | None
    end_us: int | None


@dataclass(frozen=True)
class AggregateRow:
    key: str
    label: str
    usage: TokenUsage
    cost: CostBreakdown
    credits: CreditBreakdown = field(default_factory=CreditBreakdown)
    record_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "record_count": self.record_count,
            "usage": self.usage.to_dict(),
            "cost": self.cost.to_dict(),
            "credits": self.credits.to_dict(),
        }


@dataclass(frozen=True)
class UsageSummary:
    usage: TokenUsage
    cost: CostBreakdown
    record_count: int
    credits: CreditBreakdown = field(default_factory=CreditBreakdown)

    def to_dict(self) -> dict[str, object]:
        return {
            "record_count": self.record_count,
            "usage": self.usage.to_dict(),
            "cost": self.cost.to_dict(),
            "credits": self.credits.to_dict(),
        }

    def add(self, other: UsageSummary) -> UsageSummary:
        return UsageSummary(
            usage=self.usage.add(other.usage),
            cost=self.cost.add(other.cost),
            credits=self.credits.add(other.credits),
            record_count=self.record_count + other.record_count,
        )


def resolve_timezone(name: str | None) -> tzinfo:
    if not name:
        return datetime.now().astimezone().tzinfo or UTC
    if name.casefold() in {"utc", "etc/utc", "z"}:
        return UTC
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {name}") from exc


def filter_records_by_range(
    records: list[UsageRecord],
    range_name: str,
    timezone: tzinfo,
    now: datetime | None = None,
    *,
    bounds: RangeBounds | None = None,
) -> list[UsageRecord]:
    bounds = bounds or resolve_range_bounds(range_name, timezone, now)
    if bounds.start_us is None and bounds.end_us is None:
        return records
    return [
        record
        for record in records
        if (bounds.start_us is None or datetime_to_utc_microseconds(record.timestamp) >= bounds.start_us)
        and (bounds.end_us is None or datetime_to_utc_microseconds(record.timestamp) < bounds.end_us)
    ]


def resolve_range_bounds(
    range_name: str,
    timezone: tzinfo,
    now: datetime | None = None,
) -> RangeBounds:
    start, end = resolve_local_range_datetimes(range_name, timezone, now)
    return RangeBounds(
        start_us=datetime_to_utc_microseconds(start) if start is not None else None,
        end_us=datetime_to_utc_microseconds(end) if end is not None else None,
    )


def resolve_local_range_datetimes(
    range_name: str,
    timezone: tzinfo,
    now: datetime | None = None,
) -> tuple[datetime | None, datetime | None]:
    if range_name == "all":
        return None, None
    if range_name not in RANGE_CHOICES:
        raise ValueError(f"Unknown range: {range_name}")

    now_local = (now or datetime.now(timezone)).astimezone(timezone)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    if range_name == "today":
        start, end = today_start, tomorrow_start
    elif range_name == "yesterday":
        start, end = today_start - timedelta(days=1), today_start
    elif range_name == "7d":
        start, end = today_start - timedelta(days=6), tomorrow_start
    elif range_name == "30d":
        start, end = today_start - timedelta(days=29), tomorrow_start
    elif range_name == "month":
        start = today_start.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
    else:
        start, end = today_start, tomorrow_start

    return start, end


def datetime_to_utc_microseconds(timestamp: datetime) -> int:
    delta = timestamp.astimezone(UTC) - _UTC_EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def filter_records_by_project_keys(records: list[UsageRecord], project_keys: Sequence[str] | None) -> list[UsageRecord]:
    selected = {key.strip() for key in project_keys or [] if key.strip()}
    if not selected:
        return records
    return [record for record in records if record.project_key in selected or any(alias in selected for alias in record.project_aliases)]


def aggregate_records(records: list[UsageRecord], group_by: str, timezone: tzinfo) -> list[AggregateRow]:
    if group_by not in GROUP_CHOICES:
        raise ValueError(f"Unknown grouping: {group_by}")

    buckets: dict[str, tuple[str, UsageSummary]] = {}
    for record in records:
        key, label = _bucket_key(record, group_by, timezone)
        existing_label, existing_summary = buckets.get(key, (label, _empty_summary()))
        buckets[key] = (existing_label, existing_summary.add(summarize_record(record)))

    rows = [
        AggregateRow(
            key=key,
            label=label,
            usage=summary.usage,
            cost=summary.cost,
            credits=summary.credits,
            record_count=summary.record_count,
        )
        for key, (label, summary) in buckets.items()
    ]
    if group_by in {"day", "hour"}:
        return sorted(rows, key=lambda row: row.key)
    return sorted(rows, key=lambda row: row.usage.total_tokens, reverse=True)


def summarize_records(records: list[UsageRecord]) -> UsageSummary:
    summary = _empty_summary()
    for record in records:
        summary = summary.add(summarize_record(record))
    return summary


def summarize_record(record: UsageRecord) -> UsageSummary:
    return UsageSummary(
        usage=record.usage,
        cost=_record_cost(record),
        credits=_record_credits(record),
        record_count=1,
    )


def _empty_summary() -> UsageSummary:
    return UsageSummary(
        usage=TokenUsage(),
        cost=CostBreakdown(),
        credits=CreditBreakdown(),
        record_count=0,
    )


def _bucket_key(record: UsageRecord, group_by: str, timezone: tzinfo) -> tuple[str, str]:
    local_timestamp = record.timestamp.astimezone(timezone)
    if group_by == "day":
        key = local_timestamp.strftime("%Y-%m-%d")
        return key, key
    if group_by == "hour":
        key = local_timestamp.strftime("%Y-%m-%d %H:00")
        return key, key
    if group_by == "project":
        return record.project_key, record.project_label
    if group_by == "model":
        return record.model, record.model
    return record.session_id, record.session_id


def _record_cost(record: UsageRecord) -> CostBreakdown:
    cost = estimate_cost(record.usage, record.model, at=record.timestamp)
    if cost is not None:
        return cost
    return CostBreakdown(unpriced_tokens=record.usage.total_tokens)


def _record_credits(record: UsageRecord) -> CreditBreakdown:
    credits = estimate_codex_credits(record.usage, record.model, at=record.timestamp)
    if credits is not None:
        return credits
    return CreditBreakdown(unpriced_tokens=record.usage.total_tokens)
