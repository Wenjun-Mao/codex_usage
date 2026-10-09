"""Captured continuity and exact-interval calibration, never a replacement meter."""
from datetime import datetime
from math import isclose

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_pace_evidence import prepare_pace_evidence
from codex_usage.allowance_queries import load_quota_evidence
from codex_usage.breakdown_windows import observed_windows
from codex_usage.breakdown_balances import prepare_balances


def weekly_anchors(status):
    anchors = [QuotaObservation(**{k: b[k] for k in QuotaObservation.__dataclass_fields__})
               for b in status["active_buckets"] if b["duration_minutes"] == 10080]
    return list({(p.limit_id, p.duration_minutes, p.timestamp, p.plan, p.used_percent,
                     p.resets_at, p.reset_credits): p for p in anchors}.values())


def prepare_evidence(connection, report, now):
    points, provenance, live = load_quota_evidence(connection)
    anchors = weekly_anchors(report["status"])
    prepared = prepare_pace_evidence(points, live)
    reason = "weekly live evidence unavailable"
    cycle = None
    if len(anchors) > 1:
        reason = "ambiguous active weekly series"
    elif anchors:
        anchor = anchors[0]
        evidence = prepared.cycle(anchor)
        age = (now - datetime.fromisoformat(anchor.timestamp)).total_seconds()
        reason = ("stale weekly anchor" if age > 3600 else "future weekly anchor" if age < 0 else
                  "weekly live probe incomplete or failed" if report["status"]["probe_status"] != "fresh" else
                  "weekly reset deadline elapsed or unavailable" if anchor.resets_at is None or anchor.resets_at <= now.timestamp() else
                  evidence.boundary if evidence.first is None else "")
        if not reason:
            cycle = {"start": evidence.first.timestamp, "end": anchor.timestamp,
                     "limit_id": anchor.limit_id, "duration_minutes": anchor.duration_minutes,
                     "plan": evidence.plan, "boundary": evidence.boundary,
                     "full_at": evidence.reported_full_at, "corrections": evidence.corrections}
    # Preserve every reading, identity and source, including conflicting points.
    captured = [dict(p.to_dict(), provenance=", ".join(sorted(provenance[p]))) for p in points]
    return {"cycle": cycle, "reason": reason, "points": captured,
            "windows": observed_windows(prepared), "balances": prepare_balances(connection),
            "paces": report.get("paces", [])}


def interval_calibration(evidence, start, end, allowance_cost, unpriced, complete):
    """Only an already established exact causal interval can support attribution."""
    cycle = evidence["cycle"]
    reason = ("incomplete local coverage" if not complete else
              "no compatible continuous weekly evidence" if not cycle else
              "ambiguous weekly portion" if cycle.get("ambiguous") else
              "unknown interval cost" if unpriced else
              "interval outside observed cycle" if start < datetime.fromisoformat(cycle["start"]).timestamp()
              or end > datetime.fromisoformat(cycle["end"]).timestamp() else
              "full-meter / credit-funded cutoff" if cycle["full_at"] is not None and end >= cycle["full_at"] else "")
    if not reason:
        for series in evidence["paces"]:
            for pace in series:
                reference = pace.get("reference")
                if (pace.get("method") == "calibrated cost" and reference
                    and pace.get("limit_id") == cycle["limit_id"]
                    and pace.get("duration_minutes") == cycle["duration_minutes"]
                    and pace.get("anchor") == end and pace.get("span_seconds") == end - start
                    and datetime.fromisoformat(reference["available_at"]).timestamp() <= end
                    and reference["plan"] == cycle["plan"]
                    and isclose(pace["cost"], allowance_cost, rel_tol=1e-12, abs_tol=1e-12)):
                    return {"value": reference["value"], "confidence": reference["confidence"],
                            "reference_end": reference["end"], "available_at": reference["available_at"],
                            "reference_kind": "Previous window" if reference.get("previous") else "Current window retrospective fit",
                            "reason": ""}
        reason = "no capture-causal calibration for this exact interval"
    return {"value": None, "reason": reason}
