"""Small history-navigation projection; exact capture pages load the full report."""
import json

OVERVIEW_SUFFIX = ":history-overview-1"


def encode_overview(report):
    data = {}
    for name in ("display_history", "reset_history"):
        if name not in report:
            continue
        history = report[name]
        endpoints = {index for part in history["periods"] + history["uncertain"]
                     for index in (part["capture_indices"][:1] + part["capture_indices"][-1:])}
        data[name] = {key: value for key, value in history.items() if key != "captures"}
        data[name]["capture_endpoints"] = [[index, history["captures"][index]] for index in sorted(endpoints)]
    return json.dumps(data, separators=(",", ":"))


def decode_overview(payload):
    data = json.loads(payload)
    if not isinstance(data, dict) or "display_history" not in data or set(data) - {"display_history", "reset_history"}:
        raise ValueError("Invalid history overview")
    for history in data.values():
        if not isinstance(history, dict) or any(not isinstance(history.get(key), list) for key in
                ("periods", "uncertain", "cross_boundary_fit_indices", "capture_endpoints")):
            raise ValueError("Invalid history overview directory")
        if any(type(index) is not int or index < 0 for index in history["cross_boundary_fit_indices"]):
            raise ValueError("Invalid history overview cross-boundary references")
        endpoints = history.pop("capture_endpoints")
        captures = {}
        for pair in endpoints:
            if (not isinstance(pair, list) or len(pair) != 2 or type(pair[0]) is not int or pair[0] < 0
                    or pair[0] in captures or not isinstance(pair[1], dict)
                    or not isinstance(pair[1].get("timestamp"), str)):
                raise ValueError("Invalid history overview endpoint")
            captures[pair[0]] = pair[1]
        for fragment in history["periods"] + history["uncertain"]:
            if not isinstance(fragment, dict) or any(not isinstance(fragment.get(key), list)
                    or any(type(i) is not int or i < 0 for i in fragment[key])
                    for key in ("capture_indices", "fit_indices")):
                raise ValueError("Invalid history overview references")
            indices = fragment["capture_indices"]
            if not indices or any(i not in captures for i in (indices[0], indices[-1])):
                raise ValueError("Missing history overview endpoint")
        history["captures"] = captures
    return data
