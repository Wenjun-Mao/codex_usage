"""Store historical windows once while preserving the complete report shape."""
import json

REPORT_CACHE_FORMAT_REVISION = 1
REPORT_FORMAT = f"allowance-window-references-{REPORT_CACHE_FORMAT_REVISION}"


def encode_report(report):
    windows = report["windows"]
    positions = {id(window): index for index, window in enumerate(windows)}

    def reference(window):
        if window is None:
            return None
        if id(window) not in positions:
            raise ValueError("Allowance summary references a window outside the report")
        return positions[id(window)]

    data = dict(report)
    for field in ("qualified", "history"):
        data[field] = [reference(window) for window in report[field]]
    data["headline"] = reference(report["headline"])
    _validate_display_history(data)
    return json.dumps({"format": REPORT_FORMAT, "report": data})


def decode_report(payload):
    encoded = json.loads(payload)
    if encoded.get("format") != REPORT_FORMAT:
        return encoded
    report = encoded["report"]
    windows = report["windows"]

    def window(index):
        if type(index) is not int or not 0 <= index < len(windows):
            raise ValueError("Invalid allowance window reference")
        return windows[index]

    for field in ("qualified", "history"):
        report[field] = [window(index) for index in report[field]]
    if report["headline"] is not None:
        report["headline"] = window(report["headline"])
    _validate_display_history(report)
    return report


def _validate_display_history(report):
    """Display references own raw captures and fits exactly once, not copies."""
    history = report.get("display_history")
    if history is None:
        return

    def indices(values, size):
        if any(type(index) is not int or not 0 <= index < size for index in values):
            raise ValueError("Invalid allowance display reference")
        return values

    captures, fits = [], list(indices(history["cross_boundary_fit_indices"], len(report["windows"])))
    for fragment in history["periods"] + history["uncertain"]:
        captures.extend(indices(fragment["capture_indices"], len(history["captures"])))
        fits.extend(indices(fragment["fit_indices"], len(report["windows"])))
    if sorted(captures) != list(range(len(history["captures"]))) or sorted(fits) != list(range(len(report["windows"]))):
        raise ValueError("Allowance display references must have exactly one owner")
