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
    return report
