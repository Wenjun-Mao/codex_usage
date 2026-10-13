"""Cache references preserve monetary reports and legacy payload compatibility."""
import json

import pytest

from codex_usage.allowance_report_codec import REPORT_FORMAT, decode_report, encode_report


def report():
    windows = [dict(limit_id="codex", start=f"day-{i}", estimate={"value": .1+i},
        points=[dict(timestamp=f"{i}-{j}", used_percent=j, provenance="Live probe") for j in range(100)])
        for i in range(3)]
    return dict(windows=windows, headline=windows[1], qualified=[windows[0], windows[2]],
        history=list(reversed(windows)), headline_previous=True, status={"fresh": True},
        credits=[{"balance": "0.000000000000000001"}], paces=[{"reference": {"value": .3}}])


def test_roundtrip_retains_values_order_and_shared_window_ownership():
    original = report()
    encoded = encode_report(original)
    restored = decode_report(encoded)
    assert restored == original
    assert restored["headline"] is restored["windows"][1]
    assert restored["qualified"][1] is restored["windows"][2]
    assert restored["history"][0] is restored["windows"][2]
    assert len(encoded) < .6*len(json.dumps(original))
    assert original["headline"] is original["windows"][1]
    assert len(original["history"]) == 3


def test_legacy_payload_is_still_readable():
    original = report()
    assert decode_report(json.dumps(original)) == original


def test_empty_report_and_no_headline_roundtrip():
    original = dict(windows=[], headline=None, qualified=[], history=[], status={"fresh": False})
    assert decode_report(encode_report(original)) == original


@pytest.mark.parametrize("index", [-1, 3, True, "1", None])
def test_invalid_window_reference_is_rejected(index):
    encoded = json.loads(encode_report(report()))
    encoded["report"]["history"][0] = index
    assert encoded["format"] == REPORT_FORMAT
    with pytest.raises(ValueError):
        decode_report(json.dumps(encoded))


def test_foreign_summary_window_is_rejected():
    original = report()
    original["headline"] = dict(original["windows"][0])
    with pytest.raises(ValueError, match="outside the report"):
        encode_report(original)
