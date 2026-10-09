"""Compact fixed-gutter ticks without losing exact balance evidence."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from codex_usage.report_breakdown_balances import balance_ticks, balances
from codex_usage.report_breakdown_numbers import compact_decimal
from codex_usage.report_usage_breakdown_chart import plot


@pytest.mark.parametrize("value,signed,expected", [
    ("62460.000000000000000001", False, "62460"),
    ("62459.0000", False, "62459"),
    ("2.000000000000000000", True, "+2"),
    ("-2.000000000000000000", True, "-2"),
    ("0.123456", False, "0.123456"),
    ("0.000001", False, "0.000001"),
    ("0.000000000000000001", True, "+1e-18"),
    ("-0.000000000000000001", True, "-1e-18"),
    ("1000000000000000000", True, "+1e18"),
    ("-1000000000000000000", True, "-1e18"),
    ("-0.000000000000000000", True, "0"),
])
def test_compact_credit_ticks(value, signed, expected):
    label = compact_decimal(Decimal(value), signed=signed)
    assert label == expected and len(label) <= 8


def test_offset_distinguishes_tiny_movement_near_maximum_valid_balance():
    minimum = Decimal("999999999999999999.999999999999999998")
    maximum = Decimal("1000000000000000000")
    axis, offset = balance_ticks(minimum, maximum)
    assert offset == minimum
    for text in ("2e-18", "1e-18", "0"):
        assert f'>{text}</span>' in axis
    assert 'title="999999999999999999.999999999999999999 credits"' in axis
    assert 'title="1000000000000000000 credits"' in axis
    at = datetime(2026, 10, 9, 12, tzinfo=UTC)
    points = [{"timestamp": (at+timedelta(hours=i)).isoformat(),
        "origin": at.isoformat() if i else None, "balance": format(value, "f"),
        "change": "0.000000000000000002" if i else None,
        "plan": "pro", "unlimited": False, "diagnostic": "", "reason": "first capture"}
        for i, value in enumerate((minimum, maximum))]
    document = balances(points, at.timestamp(), at.timestamp()+3600, UTC)
    assert f'Axis offset: +{minimum} credits' in document
    assert 'cy="140.000"' in document and 'cy="0.000"' in document
    assert "Increase +0.000000000000000002 credits" in document
    assert f'balance {minimum} credits' in document


def test_plain_range_keeps_absolute_ticks_and_no_offset():
    axis, offset = balance_ticks(Decimal("62458.000000000000000001"), Decimal("62460.000000000000000001"))
    assert offset is None
    assert all(f'>{value}</span>' in axis for value in ("62460", "62459", "62458"))


@pytest.mark.parametrize("value", [100_000_000, 171_858_000, 1_000_000_000])
def test_realistic_token_scale_uses_shared_compact_ticks(value):
    document = plot([{"model": value}], metric="tokens", labels=["model"])
    assert f'title="{value} tokens"' in document
    assert f'>{compact_decimal(value)}</span>' in document
    assert len(compact_decimal(value)) <= 8
