"""Full prospective account-read adjacency, exact decimals and day partitions."""
from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from codex_usage.allowance_credits import _has_credit_schema, decimal_balance


def prepare_balances(connection):
    if not _has_credit_schema(connection):
        return []
    rows = connection.execute("""select r.read_id, r.timestamp, r.plan,
        c.balance, c.unlimited, c.has_credits, c.diagnostic
        from quota_reads r left join credit_observations c using(read_id)
        order by r.read_id""").fetchall()
    observations = []
    previous = None
    for row in rows:
        point = dict(row)
        point["balance"] = decimal_balance(point["balance"])
        point.update(change=None, origin=None, reason="first retained capture")
        if previous is not None:
            point["origin"] = previous["timestamp"]
            reason = ("missing or invalid balance" if any(p["balance"] is None or p["diagnostic"] for p in (point, previous)) else
                "unlimited balance" if point["unlimited"] or previous["unlimited"] else
                "plan unavailable or changed" if not point["plan"] or point["plan"] != previous["plan"] else
                "nonchronological captures" if datetime.fromisoformat(point["timestamp"]) <= datetime.fromisoformat(previous["timestamp"]) else "")
            point["reason"] = reason
            if not reason:
                with localcontext() as context:
                    context.prec = 40
                    point["change"] = format(Decimal(point["balance"]) - Decimal(previous["balance"]), "f")
        observations.append(point)
        previous = point
    return observations


def balance_partitions(points, timezone):
    partitions = {}
    for point in points:
        end = datetime.fromisoformat(point["timestamp"]).astimezone(timezone).date()
        start = datetime.fromisoformat(point["origin"] or point["timestamp"]).astimezone(timezone).date()
        # Preserve long original intervals in every intersecting day; never
        # spread their change among hours. Backwards captures remain raw points.
        day = min(start, end)
        while day <= end:
            partitions.setdefault("balance:" + day.isoformat(), []).append(point)
            day += timedelta(days=1)
    return partitions
