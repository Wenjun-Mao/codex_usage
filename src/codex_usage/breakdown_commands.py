"""Issued-command validation separates expiry from malformed/unissued input."""
import json
import hashlib
from datetime import UTC, datetime, timedelta

RECEIPT_PREFIX = "breakdown-issued:"
RECEIPT_MAX_SCOPES = 256
RECEIPT_TTL_HOURS = 24


def action_hash(action):
    return hashlib.sha256(json.dumps(action, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def receipt(actions):
    return {"action_hashes": [action_hash(action) for action in actions]}


def prune_receipts(connection, *, now=None):
    """Own bounded recovery proofs, independently of rendered generation data."""
    cutoff = ((now or datetime.now(UTC)) - timedelta(hours=RECEIPT_TTL_HOURS)).isoformat()
    connection.execute("delete from rendered_reports where cache_key like ? and created_at < ?",
        (RECEIPT_PREFIX + "%", cutoff))
    connection.execute("""delete from rendered_reports where cache_key in (
        select cache_key from rendered_reports where cache_key like ?
        order by created_at desc, cache_key desc limit -1 offset ?)""",
        (RECEIPT_PREFIX + "%", RECEIPT_MAX_SCOPES))


class BreakdownScopeExpired(ValueError):
    """A previously issued action no longer belongs to current evidence scope."""


def issued_action(connection, payload, load):
    try:
        args = json.loads(payload)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid breakdown action") from error
    if (not isinstance(args, dict) or set(args) != {"scope", "state"}
        or not isinstance(args["scope"], str) or len(args["scope"]) != 64
        or any(c not in "0123456789abcdef" for c in args["scope"])):
        raise ValueError("Invalid breakdown command fields")
    row = connection.execute("select created_at from rendered_reports where cache_key=?",
        (RECEIPT_PREFIX + args["scope"],)).fetchone()
    issued = load(connection, RECEIPT_PREFIX + args["scope"])
    if (not row or not issued or datetime.fromisoformat(row[0]) < datetime.now(UTC)-timedelta(hours=RECEIPT_TTL_HOURS)
        or action_hash(args) not in issued["action_hashes"]):
        raise ValueError("Unissued or unsupported breakdown command")
    return args
