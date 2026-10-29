"""Private issued states over immutable, already materialized allowance history."""
import hashlib
import json
from datetime import UTC, datetime, timedelta

from codex_usage.breakdown_commands import action_hash, receipt, RECEIPT_TTL_HOURS

PERIOD_LIMIT = 12
CAPTURE_LIMIT = 100
FIT_LIMIT = 12
RECEIPT_PREFIX = "allowance-issued:"
DEFAULT_STATE = dict(period_page=0, uncertain_page=0, kind="", index=-1,
                     fit_page=0, capture_page=0, capture_order="newest")


def report_history(report):
    return report.get("reset_history", report["display_history"])


class AllowanceScopeExpired(ValueError):
    """A real issued command no longer belongs to this report/account scope."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_state(state):
    if not isinstance(state, dict) or set(state) != set(DEFAULT_STATE):
        raise ValueError("Invalid allowance history state fields")
    for key in ("period_page", "uncertain_page", "fit_page", "capture_page", "index"):
        if type(state[key]) is not int or not (-1 if key == "index" else 0) <= state[key] <= 2**31-1:
            raise ValueError("Invalid allowance history index")
    if state["kind"] not in ("", "periods", "uncertain", "cross") or state["capture_order"] not in ("newest", "oldest"):
        raise ValueError("Invalid allowance history selection")
    if state["kind"] in ("", "cross") and state["index"] != -1:
        raise ValueError("Invalid allowance history owner")
    if state["kind"] in ("periods", "uncertain") and state["index"] < 0:
        raise ValueError("Invalid allowance history owner")
    return dict(state)


def validate_action(value):
    if (not isinstance(value, dict) or set(value) != {"scope", "state"}
            or not isinstance(value["scope"], str) or len(value["scope"]) != 64
            or any(c not in "0123456789abcdef" for c in value["scope"])):
        raise ValueError("Invalid allowance history action")
    return dict(scope=value["scope"], state=validate_state(value["state"]))


def issued_state(connection, payload, context, load, *, selection_context=None):
    try:
        action = validate_action(json.loads(payload))
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid allowance history command") from error
    key = RECEIPT_PREFIX + action["scope"]
    row = connection.execute("select created_at from rendered_reports where cache_key=?", (key,)).fetchone()
    issued = load(connection, key)
    if (not row or not issued or action_hash(action) not in issued["action_hashes"]
            or datetime.fromisoformat(row[0]) < datetime.now(UTC)-timedelta(hours=RECEIPT_TTL_HOURS)):
        raise ValueError("Unissued allowance history command")
    if issued["context"] != context and (selection_context is None
            or issued.get('selection_context') != selection_context):
        raise AllowanceScopeExpired("Issued allowance history scope expired; reload without history commands")
    return action["state"]


def page_slice(values, page, size, *, newest=False):
    if newest:
        end = max(0, len(values)-page*size)
        return list(reversed(values[max(0, end-size):end]))
    return values[page*size:(page+1)*size]


def selection(history, state):
    kind = state["kind"]
    if kind in ("periods", "uncertain"):
        return history[kind][state["index"]]
    return {"fit_indices": history["cross_boundary_fit_indices"] if kind == "cross" else [], "capture_indices": []}


def navigation(report, context, state=None):
    state = validate_state(DEFAULT_STATE if state is None else state)
    history = report_history(report)
    for kind in ("periods", "uncertain"):
        if state[("period" if kind == "periods" else kind) + "_page"] > max(0, (len(history[kind])-1)//PERIOD_LIMIT):
            raise ValueError("Allowance history page outside report")
    if state["kind"] in ("periods", "uncertain") and state["index"] >= len(history[state["kind"]]):
        raise ValueError("Allowance history owner outside report")
    if state["kind"] in ("periods", "uncertain"):
        page_field = "period_page" if state["kind"] == "periods" else "uncertain_page"
        if state["index"]//PERIOD_LIMIT != state[page_field]:
            raise ValueError("Allowance owner outside visible page")
    elif state["kind"] == "cross" and not history["cross_boundary_fit_indices"]:
        raise ValueError("No cross-boundary fits in report")
    owner = selection(history, state)
    for field, values, size in (("capture_page", owner["capture_indices"], CAPTURE_LIMIT),
                                ("fit_page", owner["fit_indices"], FIT_LIMIT)):
        if state[field] > max(0, (len(values)-1)//size):
            raise ValueError("Allowance detail page outside owner")
    scope = digest([context, state])
    nav = dict(scope=scope, state=state, actions=[])

    def issue(target):
        action = dict(scope=scope, state=target)
        if action not in nav["actions"]:
            nav["actions"].append(action)

    issue(state)
    clear = dict(kind="", index=-1, fit_page=0, capture_page=0, capture_order="newest")
    for kind, field in (("periods", "period_page"), ("uncertain", "uncertain_page")):
        count = len(history[kind])
        for page in (state[field]-1, state[field]+1):
            if 0 <= page <= max(0, (count-1)//PERIOD_LIMIT):
                issue(dict(state, **clear, **{field: page}))
        for index in range(state[field]*PERIOD_LIMIT, min(count, (state[field]+1)*PERIOD_LIMIT)):
            issue(dict(state, kind=kind, index=index, fit_page=0, capture_page=0, capture_order="newest"))
    if history["cross_boundary_fit_indices"]:
        issue(dict(state, kind="cross", index=-1, fit_page=0, capture_page=0, capture_order="newest"))
    for field, values, size in (("capture_page", owner["capture_indices"], CAPTURE_LIMIT),
                                ("fit_page", owner["fit_indices"], FIT_LIMIT)):
        for page in (state[field]-1, state[field]+1):
            if 0 <= page <= max(0, (len(values)-1)//size):
                issue(dict(state, **{field: page}))
    if owner["capture_indices"]:
        issue(dict(state, capture_page=0, capture_order="oldest" if state["capture_order"] == "newest" else "newest"))
    return nav


def issued_receipt(nav, context):
    return dict(receipt(nav["actions"]), context=context)
