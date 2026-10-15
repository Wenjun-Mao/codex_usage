"""Cache references preserve monetary reports and legacy payload compatibility."""
import json

import pytest

from codex_usage.allowance_report_codec import LEGACY_REPORT_FORMAT, REPORT_FORMAT, decode_report, encode_report


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


def _legacy_payload(original):
    data = dict(original)
    positions = {id(window): index for index, window in enumerate(original["windows"])}
    data["headline"] = positions[id(original["headline"])] if original["headline"] is not None else None
    for key in ("history", "qualified"):
        data[key] = [positions[id(window)] for window in original[key]]
    return json.dumps({"format": LEGACY_REPORT_FORMAT, "report": data})


def test_format_one_wrapped_payload_still_restores_exact_window_shape():
    original = report()
    restored = decode_report(_legacy_payload(original))
    assert restored == original
    assert restored["headline"] is restored["windows"][1]


def large_display_report():
    from datetime import UTC, datetime, timedelta
    start = datetime(2026, 1, 1, tzinfo=UTC)
    captures, windows, periods = [], [], []
    for index in range(120):
        points = [dict(timestamp=(start + timedelta(minutes=index*100+j)).isoformat(),
                       limit_id="codex", slot="primary", plan="pro", used_percent=j,
                       duration_minutes=300, resets_at=1800000000, reset_credits=3,
                       provenance="Live probe, Task snapshot") for j in range(100)]
        offset = len(captures)
        captures.extend(points)
        windows.append(dict(points=points, estimate={"value": index + .5}))
        periods.append(dict(capture_indices=list(range(offset, offset+100)), fit_indices=[index]))
    return dict(windows=windows, qualified=windows[:3], history=windows[::-1], headline=windows[-1],
                display_history=dict(captures=captures, periods=periods, uncertain=[], cross_boundary_fit_indices=[]))


def test_large_history_serializes_captures_once_and_restores_shared_point_ownership():
    original = large_display_report()
    before = json.dumps(original)
    payload = encode_report(original)
    encoded = json.loads(payload)
    assert len(encoded["captures"]) == 12000
    assert "captures" not in encoded["report"]["display_history"]
    assert all("points" not in window for window in encoded["report"]["windows"])
    assert payload.count('"timestamp"') == 12000
    assert len(payload) < 1.12 * len(_legacy_payload({k: v for k, v in original.items() if k != "display_history"}))
    restored = decode_report(payload)
    assert restored == original
    for index, window in enumerate(restored["windows"]):
        assert window["points"][0] is restored["display_history"]["captures"][index*100]
    assert restored["headline"] is restored["windows"][-1]
    assert json.dumps(original) == before


@pytest.mark.parametrize("bad_index", [-1, 300, True, "0", None])
def test_invalid_point_reference_is_rejected(bad_index):
    encoded = json.loads(encode_report(report()))
    encoded["report"]["windows"][0]["point_indices"][0] = bad_index
    with pytest.raises(ValueError, match="capture.*reference"):
        decode_report(json.dumps(encoded))


@pytest.mark.parametrize("damage", ["pool-duplicate", "point-duplicate", "inline-points", "inline-captures", "foreign-point"])
def test_ambiguous_capture_ownership_is_rejected(damage):
    original = large_display_report()
    if damage == "foreign-point":
        original["windows"][0]["points"] = [dict(timestamp="foreign")]
        with pytest.raises(ValueError, match="outside display history"):
            encode_report(original)
        return
    encoded = json.loads(encode_report(original))
    if damage == "pool-duplicate":
        encoded["captures"].append(dict(encoded["captures"][0]))
    elif damage == "point-duplicate":
        encoded["report"]["windows"][0]["point_indices"] = [0, 0]
    elif damage == "inline-points":
        encoded["report"]["windows"][0]["points"] = []
    else:
        encoded["report"]["display_history"]["captures"] = []
    with pytest.raises(ValueError):
        decode_report(json.dumps(encoded))
