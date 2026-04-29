from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.pricing import CostBreakdown, estimate_cost


RANGE_CHOICES = ("today", "yesterday", "7d", "30d", "month", "all")
GROUP_CHOICES = ("day", "hour", "project", "model", "session")


@dataclass(frozen=True)
class AggregateRow:
    key: str
    label: str
    usage: TokenUsage
    cost: CostBreakdown
    record_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "record_count": self.record_count,
            "usage": self.usage.to_dict(),
            "cost": self.cost.to_dict(),
        }


@dataclass(frozen=True)
class UsageSummary:
    usage: TokenUsage
    cost: CostBreakdown
    record_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "record_count": self.record_count,
            "usage": self.usage.to_dict(),
            "cost": self.cost.to_dict(),
        }


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
) -> list[UsageRecord]:
    if range_name == "all":
        return records
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

    return [record for record in records if start <= record.timestamp.astimezone(timezone) < end]


def aggregate_records(records: list[UsageRecord], group_by: str, timezone: tzinfo) -> list[AggregateRow]:
    if group_by not in GROUP_CHOICES:
        raise ValueError(f"Unknown grouping: {group_by}")

    buckets: dict[str, tuple[str, TokenUsage, CostBreakdown, int]] = {}
    for record in records:
        key, label = _bucket_key(record, group_by, timezone)
        _, usage, cost, count = buckets.get(key, (label, TokenUsage(), CostBreakdown(), 0))
        buckets[key] = (
            label,
            usage.add(record.usage),
            cost.add(_record_cost(record)),
            count + 1,
        )

    rows = [
        AggregateRow(key=key, label=label, usage=usage, cost=cost, record_count=count)
        for key, (label, usage, cost, count) in buckets.items()
    ]
    if group_by in {"day", "hour"}:
        return sorted(rows, key=lambda row: row.key)
    return sorted(rows, key=lambda row: row.usage.total_tokens, reverse=True)


def summarize_records(records: list[UsageRecord]) -> UsageSummary:
    usage = TokenUsage()
    cost = CostBreakdown()
    for record in records:
        usage = usage.add(record.usage)
        cost = cost.add(_record_cost(record))
    return UsageSummary(usage=usage, cost=cost, record_count=len(records))


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
    cost = estimate_cost(record.usage, record.model)
    if cost is not None:
        return cost
    return CostBreakdown(unpriced_tokens=record.usage.total_tokens)
