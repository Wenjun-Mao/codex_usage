"""Compact pace copy preserves forecast semantics and local-time evidence."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest

from codex_usage.report_allowance_pace import pace_rows, reset_gap_label


class PaceMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.words = []
        self.times = []
        self.feed(html)

    def handle_data(self, text):
        self.words.append(text)

    def handle_starttag(self, tag, attrs):
        if tag == "time":
            self.times.append(dict(attrs))

    @property
    def text(self):
        return "".join(self.words)


def pace(exhaustion, *, anchor=None, reset=None, name="Recent", span=3600, balance=-1):
    anchor = anchor or datetime(2026, 10, 2, 15, 34, tzinfo=UTC)
    reset = reset or datetime(2026, 10, 7, 19, 50, tzinfo=UTC)
    return {"name": name, "span_seconds": span, "anchor": anchor.timestamp(),
            "reset": reset.timestamp(), "used": 60, "rate": 4,
            "exhaustion": exhaustion.timestamp(), "reset_balance": balance}


def render(rows, *, now=None, timezone="America/Toronto"):
    now = now or datetime.fromtimestamp(rows[0]["anchor"], UTC)
    return PaceMarkup(pace_rows(rows, "fresh", timezone=ZoneInfo(timezone), now=now))


def test_compact_copy_uses_actual_spans_relative_days_and_approximate_reset_gaps():
    rows = [
        pace(datetime(2026, 10, 2, 20, 30, tzinfo=UTC)),
        pace(datetime(2026, 10, 3, 3, 45, tzinfo=UTC), name="Daily", span=23*3600+51*60),
        pace(datetime(2026, 10, 3, 20, 45, tzinfo=UTC), name="Cycle", span=43*3600+42*60),
    ]
    saved = deepcopy(rows)
    markup = render(rows)
    assert "Recent · 1h: Estimated to run out today, 16:30 EDT · ~4d 23h before reset." in markup.text
    assert "Daily · 23h 51m: Estimated to run out today, 23:45 EDT · ~4d 16h before reset." in markup.text
    assert "Cycle average · 1d 19h 42m: Estimated to run out tomorrow, 16:45 EDT · ~3d 23h before reset." in markup.text
    assert "At this pace" not in markup.text and "observed" not in markup.text
    assert "UTC" not in markup.text and "-0400" not in markup.text
    assert all("UTC-04:00" in item["title"] for item in markup.times)
    assert all(item["title"] == item["aria-label"] for item in markup.times)
    assert rows == saved


def test_later_days_keep_calendar_date():
    markup = render([pace(datetime(2026, 10, 4, 20, 45, tzinfo=UTC))])
    assert "2026-10-04, 16:45 EDT" in markup.text
    assert markup.times[0]["datetime"] == "2026-10-04T16:45:00-04:00"


@pytest.mark.parametrize("hour,abbreviation,offset", [(5, "EDT", "-04:00"), (6, "EST", "-05:00")])
def test_repeated_dst_hour_is_disambiguated_in_time_metadata(hour, abbreviation, offset):
    anchor = datetime(2026, 11, 1, 5, tzinfo=UTC)
    exhaustion = datetime(2026, 11, 1, hour, 15, tzinfo=UTC)
    markup = render([pace(exhaustion, anchor=anchor, reset=anchor+timedelta(days=1))])
    assert f"today, 01:15 {abbreviation}" in markup.text
    assert markup.times[0]["title"] == f"2026-11-01 01:15 {abbreviation} (UTC{offset})"
    assert markup.times[0]["datetime"] == f"2026-11-01T01:15:00{offset}"


def test_fractional_positive_timezone_offset_is_preserved():
    markup = render([pace(datetime(2026, 10, 2, 20, 30, tzinfo=UTC))], timezone="Asia/Kolkata")
    assert "tomorrow, 02:00 IST" in markup.text
    assert markup.times[0]["title"] == "2026-10-03 02:00 IST (UTC+05:30)"


@pytest.mark.parametrize("delta", [-900, 0, 900])
def test_near_reset_stays_conditional_at_existing_boundary(delta):
    anchor = datetime(2026, 10, 2, 15, 34, tzinfo=UTC)
    reset = anchor + timedelta(hours=3)
    markup = render([pace(reset+timedelta(seconds=delta), anchor=anchor, reset=reset)])
    assert "Estimated to run out near reset." in markup.text
    assert not markup.times


@pytest.mark.parametrize("balance,remaining", [(32.1, "32%"), (0.2, "less than 1%")])
def test_remaining_at_reset_is_compact_and_unchanged(balance, remaining):
    anchor = datetime(2026, 10, 2, 15, 34, tzinfo=UTC)
    reset = anchor+timedelta(hours=3)
    markup = render([pace(reset+timedelta(hours=1), anchor=anchor, reset=reset, balance=balance)])
    assert f"About {remaining} would remain at reset." in markup.text
    assert not markup.times


@pytest.mark.parametrize("seconds,label", [(119*3600+16*60, "4d 23h"), (112*3600+5*60, "4d 16h"),
                                          (95*3600+9*60, "3d 23h"), (23*3600+59*60, "1d"),
                                          (48*3600, "2d"), (16*60, "16m")])
def test_reset_gap_rounds_only_presentation(seconds, label):
    assert reset_gap_label(seconds) == label


def test_labels_escape_markup_and_forecast_expires_without_sliding():
    row = pace(datetime(2026, 10, 2, 20, 30, tzinfo=UTC), name='<img src="x">')
    html = pace_rows([row], "fresh", timezone=ZoneInfo("America/Toronto"),
                     now=datetime.fromtimestamp(row["anchor"], UTC))
    assert "&lt;img src=&quot;x&quot;&gt;" in html and "<img" not in html
    expired = render([row], now=datetime.fromtimestamp(row["anchor"]+1800, UTC))
    assert "Forecast awaiting fresh capture" in expired.text
    assert not expired.times
