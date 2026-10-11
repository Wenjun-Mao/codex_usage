"""Strict current navigation schema, separate from historical receipt proof."""
from datetime import date

STATE_CHOICES = {"basis": {"selected"}, "view": {"time", "project"},
    "grain": {"daily", "hourly"}, "overlay": {"weekly", "balance", "none"},
    "metric": {"tokens", "cost", "credits"}, "group": {"model", "project"}}
STATE_KEYS = set(STATE_CHOICES) | {"day", "project", "detail"}


def validate_state(state):
    if not isinstance(state, dict) or set(state) != STATE_KEYS or any(not isinstance(v, str) for v in state.values()):
        raise ValueError("Invalid breakdown state fields")
    if any(state[k] not in choices for k, choices in STATE_CHOICES.items()):
        raise ValueError("Unsupported breakdown state")
    try:
        if date.fromisoformat(state["day"]).isoformat() != state["day"]:
            raise ValueError("Noncanonical breakdown day")
    except ValueError as error:
        raise ValueError("Invalid breakdown day") from error
    return state
