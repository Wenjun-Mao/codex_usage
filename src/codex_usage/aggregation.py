from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
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


@dataclass(frozen=True, slots=True)
class ReportRange:
    """A validated local-calendar report selection and its UTC query bounds.

    The product chooses calendar dates, while the durable ledger indexes UTC
    instants. Keeping both representations together prevents callers from
    accidentally treating a custom range as an arbitrary timestamp filter.
    """

    kind: str
    start_date: date | None
    end_date: date | None
    bounds: RangeBounds
    display_label: str
    timezone_name: str

    @property
    def cache_identity(self) -> str:
        """Stable identity for rendered output, including moving range bounds."""
        return ":".join(
            (
                self.kind,
                self.start_date.isoformat() if self.start_date else "",
                self.end_date.isoformat() if self.end_date else "",
                str(self.bounds.start_us or ""),
                str(self.bounds.end_us or ""),
                self.timezone_name,
            )
        )

    @property
    def uses_period_trend(self) -> bool:
        return self.kind == "all" or (
            self.kind == "custom"
            and self.start_date is not None
            and self.end_date is not None
            and (self.end_date - self.start_date).days + 1 > 90
        )


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


@dataclass(frozen=True, slots=True)
class ValuedUsageRecord:
    record: UsageRecord
    summary: UsageSummary


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


def resolve_report_range(
    range_name: str,
    timezone: tzinfo,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    now: datetime | None = None,
) -> ReportRange:
    """Resolve a supported report range to inclusive local dates and UTC bounds.

    `custom` deliberately accepts dates only. Its end date is converted to the
    next local midnight, so a DST transition cannot make an inclusive calendar
    day 23 or 25 hours short in the ledger query.
    """
    now_local = (now or datetime.now(timezone)).astimezone(timezone)
    timezone_name = _timezone_name(timezone)
    if range_name == "custom":
        start = _parse_calendar_date(start_date, "start_date")
        end = _parse_calendar_date(end_date, "end_date")
        if start > end:
            raise ValueError("start_date must be on or before end_date")
        if end > now_local.date():
            raise ValueError("custom report ranges cannot include future dates")
        start_at = datetime.combine(start, datetime.min.time(), tzinfo=timezone)
        end_at = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone)
        bounds = RangeBounds(
            start_us=datetime_to_utc_microseconds(start_at),
            end_us=datetime_to_utc_microseconds(end_at),
        )
        return ReportRange(
            kind="custom",
            start_date=start,
            end_date=end,
            bounds=bounds,
            display_label=_format_calendar_label(start, end),
            timezone_name=timezone_name,
        )

    if range_name not in RANGE_CHOICES:
        raise ValueError(f"Unknown range: {range_name}")
    if start_date is not None or end_date is not None:
        raise ValueError("start_date and end_date are only valid for range=custom")
    start_at, end_at = resolve_local_range_datetimes(range_name, timezone, now_local)
    bounds = RangeBounds(
        start_us=datetime_to_utc_microseconds(start_at) if start_at else None,
        end_us=datetime_to_utc_microseconds(end_at) if end_at else None,
    )
    if start_at is None or end_at is None:
        return ReportRange(
            kind=range_name,
            start_date=None,
            end_date=None,
            bounds=bounds,
            display_label="All time",
            timezone_name=timezone_name,
        )
    return ReportRange(
        kind=range_name,
        start_date=start_at.date(),
        end_date=(end_at - timedelta(microseconds=1)).date(),
        bounds=bounds,
        display_label={
            "today": "Today",
            "yesterday": "Yesterday",
            "7d": "Last 7 days",
            "30d": "Last 30 days",
            "month": "This month",
        }[range_name],
        timezone_name=timezone_name,
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


def _parse_calendar_date(value: str | None, field: str) -> date:
    if value is None:
        raise ValueError(f"{field} is required for range=custom")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{field} must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid calendar date") from exc


def _timezone_name(timezone: tzinfo) -> str:
    return str(getattr(timezone, "key", timezone))


def _format_calendar_label(start: date, end: date) -> str:
    if start == end:
        return f"{start.strftime('%b')} {start.day}, {start.year}"
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%b')} {start.day}\N{EN DASH}{end.day}, {start.year}"
    if start.year == end.year:
        return f"{start.strftime('%b')} {start.day}\N{EN DASH}{end.strftime('%b')} {end.day}, {start.year}"
    return f"{start.strftime('%b')} {start.day}, {start.year}\N{EN DASH}{end.strftime('%b')} {end.day}, {end.year}"


def datetime_to_utc_microseconds(timestamp: datetime) -> int:
    delta = timestamp.astimezone(UTC) - _UTC_EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def filter_records_by_project_keys(records: list[UsageRecord], project_keys: Sequence[str] | None) -> list[UsageRecord]:
    selected = {key.strip() for key in project_keys or [] if key.strip()}
    if not selected:
        return records
    return [record for record in records if record.project_key in selected or any(alias in selected for alias in record.project_aliases)]


def aggregate_records(records: list[UsageRecord], group_by: str, timezone: tzinfo) -> list[AggregateRow]:
    return aggregate_valued_records(value_records(records), group_by, timezone)


def aggregate_valued_records(
    valued_records: Sequence[ValuedUsageRecord],
    group_by: str,
    timezone: tzinfo,
) -> list[AggregateRow]:
    if group_by not in GROUP_CHOICES:
        raise ValueError(f"Unknown grouping: {group_by}")

    buckets: dict[str, tuple[str, UsageSummary]] = {}
    for valued in valued_records:
        record = valued.record
        key, label = _bucket_key(record, group_by, timezone)
        existing_label, existing_summary = buckets.get(key, (label, _empty_summary()))
        buckets[key] = (existing_label, existing_summary.add(valued.summary))

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
    return summarize_valued_records(value_records(records))


def summarize_valued_records(
    valued_records: Sequence[ValuedUsageRecord],
) -> UsageSummary:
    summary = _empty_summary()
    for valued in valued_records:
        summary = summary.add(valued.summary)
    return summary


def value_records(records: Sequence[UsageRecord]) -> tuple[ValuedUsageRecord, ...]:
    return tuple(
        ValuedUsageRecord(record=record, summary=summarize_record(record))
        for record in records
    )


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
