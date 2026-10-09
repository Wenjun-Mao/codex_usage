"""Finite indexed usage-range unions, without decoding unrelated history."""
from codex_usage.aggregation import RangeBounds


def merge_bounds(ranges):
    ordered = []
    for bounds in ranges:
        if bounds.start_us is None or bounds.end_us is None:
            raise ValueError("Usage union requires finite bounds")
        if bounds.start_us < bounds.end_us:
            ordered.append(bounds)
    merged = []
    for bounds in sorted(ordered, key=lambda b: b.start_us):
        if merged and bounds.start_us <= merged[-1].end_us:
            merged[-1] = RangeBounds(merged[-1].start_us, max(merged[-1].end_us, bounds.end_us))
        else:
            merged.append(bounds)
    return merged


def subtract_bounds(ranges, selected):
    """Reuse already-valued calendar selection; query only its missing union."""
    remaining = []
    for bounds in merge_bounds(ranges):
        lo = max(bounds.start_us, selected.start_us) if selected.start_us is not None else bounds.start_us
        hi = min(bounds.end_us, selected.end_us) if selected.end_us is not None else bounds.end_us
        if lo >= hi:
            remaining.append(bounds)
        else:
            if bounds.start_us < lo:
                remaining.append(RangeBounds(bounds.start_us, lo))
            if hi < bounds.end_us:
                remaining.append(RangeBounds(hi, bounds.end_us))
    return remaining


def usage_union_clause(ranges):
    ranges = merge_bounds(ranges)
    if not ranges:
        return "0", []
    values = ",".join("(?,?)" for _ in ranges)
    # Drive finite range seeks through the existing timestamp index; IN gives
    # each event one membership even if a caller supplies overlapping ranges.
    return (f"""ledger_usage_events.event_id in (
        with requested(start_us,end_us) as (values {values})
        select e.event_id from requested join ledger_usage_events e
        on e.timestamp_us >= requested.start_us and e.timestamp_us < requested.end_us
    )""", [value for bounds in ranges for value in (bounds.start_us, bounds.end_us)])
