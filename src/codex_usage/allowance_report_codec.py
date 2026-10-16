"""Store historical windows once while preserving the complete report shape."""
import json
import math
from collections import defaultdict

REPORT_CACHE_FORMAT_REVISION = 2
REPORT_FORMAT = f"allowance-window-references-{REPORT_CACHE_FORMAT_REVISION}"
LEGACY_REPORT_FORMAT = "allowance-window-references-1"


def _point_key(point):
    if not isinstance(point, dict):
        raise ValueError("Invalid allowance capture")
    return json.dumps(point, sort_keys=True, separators=(",", ":"))


def _index(value, size, label):
    if type(value) is not int or not 0 <= value < size:
        raise ValueError(f"Invalid allowance {label} reference")
    return value


def encode_report(report):
    windows = report["windows"]
    positions = {id(window): index for index, window in enumerate(windows)}

    def reference(window):
        if window is None:
            return None
        if id(window) not in positions:
            raise ValueError("Allowance summary references a window outside the report")
        return positions[id(window)]

    _validate_display_history(report)
    _validate_display_history(report, "reset_history")
    data = dict(report)
    for field in ("qualified", "history"):
        data[field] = [reference(window) for window in report[field]]
    data["headline"] = reference(report["headline"])
    history = report.get("display_history")
    captures = list(history["captures"]) if history is not None else []
    capture_positions = {_point_key(point): index for index, point in enumerate(captures)}
    if len(capture_positions) != len(captures):
        raise ValueError("Duplicate allowance capture")

    def point_reference(point):
        key = _point_key(point)
        if key not in capture_positions:
            if history is not None:
                raise ValueError("Allowance window capture outside display history")
            capture_positions[key] = len(captures)
            captures.append(point)
        return capture_positions[key]

    data["windows"] = [dict({key: value for key, value in window.items() if key != "points"},
                            point_indices=[point_reference(point) for point in window["points"]])
                       for window in windows]
    if history is not None:
        data["display_history"] = {key: value for key, value in history.items() if key != "captures"}
    if "reset_history" in report:
        reset = report["reset_history"]
        if reset["captures"] is not history["captures"] and reset["captures"] != history["captures"]:
            raise ValueError("Reset history must share canonical captures")
        data["reset_history"] = {key: value for key, value in reset.items() if key != "captures"}
    return json.dumps({"format": REPORT_FORMAT, "captures": captures, "report": data})


def decode_report(payload):
    encoded = json.loads(payload)
    format_id = encoded.get("format")
    if format_id not in {REPORT_FORMAT, LEGACY_REPORT_FORMAT}:
        if "format" in encoded:
            raise ValueError("Unknown allowance cache format")
        return encoded
    report = encoded["report"]
    windows = report["windows"]
    if format_id == REPORT_FORMAT:
        captures = encoded["captures"]
        if not isinstance(captures, list) or len({_point_key(p) for p in captures}) != len(captures):
            raise ValueError("Invalid or duplicate allowance captures")
        used = set()
        for item in windows:
            if "points" in item or not isinstance(item.get("point_indices"), list):
                raise ValueError("Invalid allowance window capture references")
            refs = [_index(index, len(captures), "capture") for index in item.pop("point_indices")]
            if len(refs) != len(set(refs)):
                raise ValueError("Duplicate allowance window capture reference")
            used.update(refs)
            item["points"] = [captures[index] for index in refs]
        if "display_history" in report:
            if "captures" in report["display_history"]:
                raise ValueError("Duplicated allowance capture storage")
            report["display_history"]["captures"] = captures
        elif used != set(range(len(captures))):
            raise ValueError("Unowned allowance capture")
        if "reset_history" in report:
            if "captures" in report["reset_history"]:
                raise ValueError("Duplicated reset capture storage")
            report["reset_history"]["captures"] = captures

    def window(index):
        return windows[_index(index, len(windows), "window")]

    for field in ("qualified", "history"):
        report[field] = [window(index) for index in report[field]]
    if report["headline"] is not None:
        report["headline"] = window(report["headline"])
    _validate_display_history(report)
    _validate_display_history(report, "reset_history")
    return report


def _validate_display_history(report, field="display_history"):
    """Display references own raw captures and fits exactly once, not copies."""
    history = report.get(field)
    if history is None:
        return

    def indices(values, size):
        if not isinstance(values, list) or any(type(index) is not int or not 0 <= index < size for index in values):
            raise ValueError("Invalid allowance display reference")
        return values

    captures, fits = [], list(indices(history["cross_boundary_fit_indices"], len(report["windows"])))
    for fragment in history["periods"] + history["uncertain"]:
        for edge, reason in (("reset_opening", "boundary"), ("reset_closure", "ended_by")):
            boundary = fragment.get(edge)
            if boundary is None:
                continue
            if (not isinstance(boundary, dict) or set(boundary) != {"kind", "earliest", "latest"}
                    or boundary["kind"] not in ({"scheduled reset", "reset credit decrease", "early reset"}
                                               if field == "reset_history" else {"scheduled reset", "reset credit decrease"})
                    or boundary["kind"] != fragment[reason]
                    or any(type(boundary[key]) not in (int, float) or not math.isfinite(boundary[key])
                           for key in ("earliest", "latest"))
                    or boundary["earliest"] > boundary["latest"]):
                raise ValueError("Invalid allowance reset boundary")
        captures.extend(indices(fragment["capture_indices"], len(history["captures"])))
        fits.extend(indices(fragment["fit_indices"], len(report["windows"])))
    if field == "reset_history":
        series = defaultdict(list)
        for period in history["periods"]:
            for field_name in ("identity_opening", "identity_closure"):
                edge = period.get(field_name)
                if edge is not None and (not isinstance(edge, dict)
                        or set(edge) != {"kind", "earliest", "latest"} or edge["kind"] != "plan change"
                        or any(type(edge[k]) not in (int, float) or not math.isfinite(edge[k])
                               for k in ("earliest", "latest")) or edge["earliest"] > edge["latest"]):
                    raise ValueError("Invalid reset-period identity boundary")
            numeric = ("start", "end", "usage_usd", "usage_usd_min", "usage_usd_max", "allowance_used")
            if (any(type(period.get(k)) not in (int, float) or not math.isfinite(period[k]) for k in numeric)
                    or period["start"] > period["end"]
                    or not 0 <= period["usage_usd_min"] <= period["usage_usd"] <= period["usage_usd_max"]
                    or not 0 <= period["allowance_used"] <= 100
                    or any(type(period.get(k)) is not int for k in
                           ("unpriced_tokens", "unpriced_tokens_min", "unpriced_tokens_max"))
                    or not 0 <= period["unpriced_tokens_min"] <= period["unpriced_tokens"] <= period["unpriced_tokens_max"]
                    or type(period.get("coverage_complete")) is not bool):
                raise ValueError("Invalid reset-period totals")
            chosen = period.get("allowance_fit_index")
            if chosen is None:
                if period.get("allowance_value") is not None:
                    raise ValueError("Reset allowance value has no fit")
            elif (type(chosen) is not int or chosen not in period["fit_indices"]
                  or period.get("allowance_value") != report["windows"][chosen]["estimate"]["value"]):
                raise ValueError("Invalid reset-period fit")
            series[(period["limit_id"], period["duration_minutes"])].append(period)
        for periods in series.values():
            ordered = sorted(periods, key=lambda p: (p["start"], p["end"]))
            if any(before["end"] > after["start"] for before, after in zip(ordered, ordered[1:])):
                raise ValueError("Overlapping reset periods")
    if sorted(captures) != list(range(len(history["captures"]))) or sorted(fits) != list(range(len(report["windows"]))):
        raise ValueError("Allowance display references must have exactly one owner")
