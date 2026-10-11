"""Human labels and exact extreme-balance inspection on the shared layer."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from codex_usage.report_breakdown_balances import balance_ticks
from codex_usage.report_breakdown_numbers import compact_decimal, tick_ceiling
from codex_usage.report_breakdown_overlay import overlay
from codex_usage.report_usage_breakdown_chart import COLORS, plot


@pytest.mark.parametrize("value,unit,expected", [
    (139030000, "tokens", "139.03 M"), (278050000, "tokens", "278.05 M"),
    (28.61067, "cost", "$28.61"), (57.22134, "cost", "$57.22"),
    (1230, "credits", "1.23 K"), ("0.000001", "cost", "$0.000001"),
    (0, "credits", "0"), ("-0.0", "credits", "0")])
def test_human_units(value, unit, expected):
    assert compact_decimal(value, unit=unit) == expected


def test_offset_distinguishes_extreme_finite_movement():
    minimum = Decimal("999999999999999999.999999999999999999")
    maximum = Decimal("1000000000000000000.000000000000000001")
    axis, offset = balance_ticks(minimum, maximum)
    assert offset == minimum
    assert len(set(axis.split("<span")[1:])) == 3
    assert "e-" not in axis
    at = datetime(2026, 10, 9, tzinfo=UTC)
    points = [{"timestamp": at.isoformat(), "origin": None, "balance": str(value),
        "change": None, "plan": "pro", "unlimited": False, "diagnostic": "", "reason": "first capture"}
        for value in (minimum, maximum)]
    marks, _, name, table = overlay(points, "balance", at.timestamp(), at.timestamp()+3600, UTC, COLORS, inspection=True)
    assert "Axis offset:" in name and f'balance {minimum} credits' in table
    assert '<circle class="ub-account-point"' in marks and "<svg" not in table


@pytest.mark.parametrize("value", [139030000, 278050000, 28.61067, 57.22134, .000001])
def test_tick_ceiling_contains_unmodified_values(value):
    maximum = tick_ceiling(value)
    assert maximum >= value
    metric = "tokens" if value > 1000 else "cost"
    document = plot([{"model": value}], metric=metric, labels=["model"])
    assert f'model: {value!r}' in document
    assert compact_decimal(maximum, unit=metric) in document
