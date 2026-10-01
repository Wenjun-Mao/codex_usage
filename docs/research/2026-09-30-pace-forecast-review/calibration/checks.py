"""Synthetic checks for the offline harness, not release acceptance."""
import math
from datetime import UTC, datetime

from evidence import current_suffix, plans_at_prefix, reset_boundary
from measures import DAILY, RECENT, bucketed, eligible, forecast, interval_rate, level_rate, net_rate, paired
from replay import evaluate, future_target, live_cycles, proxy_error, summarize_rows


def point(hours, used, *, reset=7 * 86400, credits=1, plan="pro", read_id=1, source="live"):
    return {"seconds": hours * 3600, "used": used, "reset": reset, "credits": credits,
            "plan": plan, "read_id": read_id, "source": source}


def close(actual, expected):
    assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9), (actual, expected)


def main():
    for values, expected in (([80, 90, 90, 90, 90], 8), ([80, 80, 90, 90, 90], 12),
                             ([80, 80, 80, 80, 90], 8)):
        samples = list(zip([0, .25, .5, .75, 1], values))
        close(level_rate(samples, None), expected)
        close(net_rate(samples), 10)
    daily = [(hours / 4 - 24, 40 + min(hours / 4, 21) + 8 * max(0, hours / 4 - 21)) for hours in range(97)]
    close(level_rate(daily, 6), 1.6620788172)
    close(interval_rate(daily, 6), 3.186936033807)
    close(net_rate(daily), 1.875)
    old = point(0, 30, reset=600)
    new = point(.25, 29.5, reset=605700, credits=0, read_id=2)
    assert reset_boundary(old, new) == "scheduled-compatible"
    assert current_suffix([old, new], new).points == [new]
    increased = point(.25, 31, reset=605700, credits=0, read_id=2)
    assert current_suffix([old, increased], increased).points == [increased]
    prefix = [point(0, 10), point(.25, 11, plan="", read_id=2), point(.5, 12, plan="", read_id=3)]
    future = point(.75, 13, plan="plus", read_id=4)
    assert plans_at_prefix(prefix) == ["pro", "pro", "pro"]
    assert current_suffix(prefix + [future], prefix[-1]).points == prefix
    assert current_suffix(prefix + [dict(prefix[-1], used=15)], prefix[-1]).conflict
    later = point(.75, 13, read_id=4)
    assert current_suffix(prefix + [dict(prefix[-1], used=15), later], later).points == [later]
    corrections = [point(hours, used, read_id=index + 1) for index, (hours, used) in
                   enumerate(zip([0, .25, .5, .75, 1], [50, 51, 50, 51, 50]))]
    close(net_rate(paired(corrections)), 0)
    selected, reason = eligible(corrections, corrections[-1], RECENT)
    assert reason == "low-net-movement" and len(selected) == 5
    burst = [point(minutes / 60, 80, read_id=index + 1) for index, minutes in
             enumerate((0, 15, 30, 45, 55, 56, 57, 58, 59))]
    burst.append(point(59.9 / 60, 90, read_id=10))
    assert bucketed(burst, 5, use_median=False)[-1][1] == 90
    close(level_rate(bucketed(burst, 5, use_median=True), None), 0)
    anchor = point(1, 90)
    value = forecast(anchor, 10)
    assert value["exhaustion"] == 7200
    assert forecast(anchor, 0) is None
    assert forecast(dict(anchor, reset=anchor["seconds"]), 10) is None
    linear = [(hours, 70 + hours) for hours in (-24, -12, -6, 0)]
    dense = [(hours, 70 + hours) for hours in (-24, -12, -6, -3, -2, -1, 0)]
    close(interval_rate(linear, 6), interval_rate(dense, 6))
    assert reset_boundary(point(0, 50, credits=1), point(.5, 50, credits=0)) == "reset-credit-decrease"
    assert reset_boundary(point(0, 50), point(.5, 49)) == ""
    assert reset_boundary(point(0, 50), point(.5, 50, reset=800000)) == "deadline-rebase"
    samples = [dict(point(hours, 10 + 2 * hours, read_id=index + 1), timestamp=f"sample-{index}")
               for index, hours in enumerate((0, .25, .5, .75, 1, 1.25))]
    cycles, mapping = live_cycles(samples)
    assert len(cycles) == 1 and future_target(samples, 0, 1, mapping) is samples[4]
    samples[3]["credits"] = 0
    samples[4]["credits"] = samples[5]["credits"] = 0
    _, mapping = live_cycles(samples)
    assert future_target(samples, 0, 1, mapping) is None
    close(proxy_error(point(0, 99), {"rate": 3}, point(1, 100)), 2)
    close(proxy_error(point(0, 99), {"rate": 3}, point(1, 100), capped=True), 0)
    missing_metadata = [point(0, 20, reset=600),
                        point(.25, 21, reset=None, credits=None, read_id=2),
                        point(.5, 22, reset=605400, credits=0, read_id=3)]
    assert current_suffix(missing_metadata, missing_metadata[-1]).points == [missing_metadata[-1]]
    conflict = dict(missing_metadata[-1], credits=1, read_id=4)
    assert current_suffix(missing_metadata + [conflict], conflict).conflict
    identities = [point(0, 10), point(.25, 11, plan="", read_id=2),
                  point(.5, 12, plan="plus", read_id=3)]
    cycles, _ = live_cycles(identities)
    assert len(cycles) == 2 and cycles[0]["closure"] == "identity-change"
    identical = [point(0, 10), point(0, 10, read_id=2), point(.5, 11, read_id=3)]
    assert len(live_cycles(identical)[0]) == 1
    targets = [point(hours, 10 + hours, read_id=index + 1) for index, hours in
               enumerate((0, .25, .5, .75, 1, 1))]
    targets[-1]["used"] = 13
    _, mapping = live_cycles(targets)
    assert future_target(targets, 0, 1, mapping) is None
    origin = dict(point(0, 5, reset=None), timestamp=datetime.fromtimestamp(0, UTC).isoformat())
    failed = {"read_id": 2, "timestamp": datetime.fromtimestamp(600, UTC).isoformat()}
    result = evaluate({"live": [origin], "points": [], "reads": [origin, failed]})
    assert result["latest"]["recent"]["reason"] == "no-live-bucket"
    assert result["latest_successful_origin"]["read_id"] == 1
    unmatched = {"seconds": 0, "used": 5, "cycle": 0, "targets": {"1": point(1, 6)},
                 "recent": {"reason": "available", "span": 1, "forecasts": {"net": {"rate": 1, "outcome": "remains", "exhaustion": 999}}},
                 "daily": {"reason": "too-few-observations", "forecasts": {}}}
    summary = summarize_rows([unmatched])["recent"]
    assert summary["methods"]["level-median"]["available"] == 0
    assert summary["matched_proxy_errors_pp"]["1"]["net"]["n"] == 0
    assert DAILY.lookback_hours == 24 and RECENT.lookback_hours == 1
    print("Offline harness synthetic invariants passed")


if __name__ == "__main__":
    main()
