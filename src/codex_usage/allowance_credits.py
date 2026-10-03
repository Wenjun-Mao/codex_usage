"""Exact, account-wide credit balances, independent of quota and token prices."""
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext


CREDIT_HISTORY_LIMIT = 100


@dataclass(frozen=True, slots=True)
class CreditBalance:
    balance: str | None = None
    has_credits: bool | None = None
    unlimited: bool | None = None
    diagnostic: str = ""


def decimal_balance(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    if isinstance(value, int) and not 0 <= value <= 10 ** 18:
        return None
    source = str(value)
    if len(source) > 64:
        return None
    try:
        parsed = Decimal(source)
    except InvalidOperation:
        return None
    if not parsed.is_finite() or parsed < 0 or parsed > Decimal("1e18"):
        return None
    if not -18 <= parsed.as_tuple().exponent <= 18:
        return None
    return format(parsed, "f")


def _parse_balance(value):
    if not isinstance(value, dict):
        return CreditBalance(diagnostic="invalid_credit_metadata")
    raw_balance = value.get("balance")
    balance = decimal_balance(raw_balance) if raw_balance is not None else None
    has_credits = value.get("hasCredits", value.get("has_credits"))
    unlimited = value.get("unlimited")
    diagnostic = ""
    if raw_balance is not None and balance is None:
        diagnostic = "invalid_credit_balance"
    if has_credits is not None and not isinstance(has_credits, bool):
        has_credits = None
        diagnostic = "invalid_credit_metadata"
    if unlimited is not None and not isinstance(unlimited, bool):
        unlimited = None
        diagnostic = "invalid_credit_metadata"
    return CreditBalance(balance, has_credits, unlimited, diagnostic)


def credit_balance(value):
    """Repeated bucket balances describe one balance, not additive balances."""
    if not isinstance(value, dict):
        return None
    buckets = [value.get("rateLimits", value)]
    multiple = value.get("rateLimitsByLimitId")
    if isinstance(multiple, dict):
        if len(multiple) > 64:
            return CreditBalance(diagnostic="too_many_credit_buckets")
        buckets.extend(multiple.values())
    readings = [_parse_balance(bucket["credits"]) for bucket in buckets
                if isinstance(bucket, dict) and bucket.get("credits") is not None]
    if not readings:
        return None
    # Compare decimal values, not their textual scale; preserve the first exact
    # representation. Conflicting scopes cannot be combined or chosen silently.
    identities = {(Decimal(item.balance) if item.balance is not None else None,
                   item.has_credits, item.unlimited, item.diagnostic) for item in readings}
    if len(identities) != 1:
        return CreditBalance(diagnostic="conflicting_credit_balances")
    return readings[0]


def _has_credit_schema(connection):
    return connection.execute(
        "select 1 from sqlite_master where type='table' and name='credit_observations'"
    ).fetchone() is not None


def credit_status(connection, *, latest_read_id=None, now=None):
    if not _has_credit_schema(connection):
        return None
    row = connection.execute("""
        select c.*, r.timestamp from credit_observations c
        join quota_reads r using(read_id)
        where (c.balance is not null or c.unlimited = 1) and c.diagnostic = ''
        order by c.read_id desc limit 1
    """).fetchone()
    if row is None:
        return None
    age = max(0, ((now or datetime.now(UTC)) - datetime.fromisoformat(row["timestamp"])).total_seconds())
    return {
        "balance": row["balance"], "has_credits": row["has_credits"],
        "unlimited": row["unlimited"], "observed_at": row["timestamp"],
        "freshness": "fresh" if row["read_id"] == latest_read_id and age <= 3600 else "stale",
    }


def credit_history(connection):
    if not _has_credit_schema(connection):
        return {"count": 0, "observations": []}
    count = connection.execute("select count(*) from credit_observations").fetchone()[0]
    rows = connection.execute("""
        select c.*, r.timestamp, r.plan from credit_observations c
        join quota_reads r using(read_id)
        order by c.read_id desc limit ?
    """, (CREDIT_HISTORY_LIMIT + 1,)).fetchall()
    observations = []
    for index, row in enumerate(rows[:CREDIT_HISTORY_LIMIT]):
        previous = rows[index + 1] if index + 1 < len(rows) else None
        change = None
        if (previous is not None and row["balance"] is not None and previous["balance"] is not None
                and not row["unlimited"] and not previous["unlimited"]
                and not row["diagnostic"] and not previous["diagnostic"]
                and row["timestamp"] > previous["timestamp"] and row["plan"] == previous["plan"]):
            with localcontext() as context:
                context.prec = 40
                change = format(Decimal(row["balance"]) - Decimal(previous["balance"]), "f")
        observations.append({"timestamp": row["timestamp"], "balance": row["balance"],
                             "unlimited": row["unlimited"], "has_credits": row["has_credits"],
                             "diagnostic": row["diagnostic"], "change": change})
    return {"count": count, "observations": observations}
