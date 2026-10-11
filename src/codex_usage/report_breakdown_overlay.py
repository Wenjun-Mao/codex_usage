"""Account-wide captured point layers for the shared usage timeline."""
import html
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext

from codex_usage.report_breakdown_balances import balance_ticks, balances
from codex_usage.breakdown_display import reduce_points
from codex_usage.report_breakdown_numbers import compact_decimal


@dataclass(frozen=True)
class CapturedLayer:
    marks: str = ""
    axis: str = ""
    name: str = ""
    key: str = ""
    evidence: str = ""


def overlay(points, kind, start, end, timezone, colors, *, width=720, height=180, inspection=False):
    layer = captured_layer(points, kind, start, end, timezone, colors,
        width=width, height=height, inspection=inspection)
    return layer.marks, layer.axis, layer.name, layer.key + layer.evidence


def captured_layer(points, kind, start, end, timezone, colors, *, width=720, height=180, inspection=False, compact_key=False):
    if kind == "none":
        return CapturedLayer()
    in_domain = [p for p in points if start <= datetime.fromisoformat(p["timestamp"]).timestamp() < end]
    if kind == "weekly":
        signatures = {}
        for p in in_domain:
            key = (datetime.fromisoformat(p["timestamp"]).timestamp(), p["limit_id"])
            signatures.setdefault(key, set()).add((p["plan"], p["duration_minutes"], p["used_percent"], p["resets_at"], p.get("reset_credits")))
        valid = [p for p in in_domain if p["duration_minutes"] == 10080 and p["plan"] and not p.get("_conflict") and 0 <= p["used_percent"] <= 100 and len(signatures[(datetime.fromisoformat(p["timestamp"]).timestamp(), p["limit_id"])]) == 1]
        series = sorted({(p["limit_id"], p["plan"]) for p in valid})
        axis = '<span>100%</span><span>50%</span><span>0%</span>'
        name = "Weekly allowance remaining · account-wide · right axis · 0–100%"
        rows = [f'<tr><td>{html.escape(p["timestamp"])}</td><td>{html.escape(str(p["limit_id"]))} / {html.escape(p["plan"] or "plan unavailable")} / {str(p["duration_minutes"]) + " min" if p["duration_minutes"] is not None else "duration unavailable"} / slot {html.escape(p["slot"])} / {html.escape(str(p["provenance"]))}</td><td>{p["used_percent"]!r}% used</td><td>{p["resets_at"]}</td><td>{html.escape(str(p.get("reset_credits")))}</td></tr>' for p in in_domain] if inspection else []
        table = '<details><summary>Exact captured allowance readings</summary><div class="table-wrap"><table><thead><tr><th>UTC reading</th><th>Series / source</th><th>Reported used</th><th>Reset Unix seconds</th><th>Reset credits (None = unavailable)</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table></div></details>'
        def coordinate(p):
            return height * p["used_percent"] / 100
        def label(p):
            return f'Weekly allowance · right axis | {p["timestamp"]} | {p["limit_id"]} / {p["plan"]} | {100-p["used_percent"]!r}% remaining | {p["provenance"]}'
        def group(p):
            return p["limit_id"], p["plan"]
        def color(p):
            index = series.index(group(p))
            return "var(--text)" if index == 0 else colors[(index-1) % len(colors)]
        def summary(p):
            return f'{p["limit_id"]} · weekly · {p["plan"]} · {compact_decimal(100-p["used_percent"])}% remaining'
    else:
        valid = [p for p in in_domain if p["balance"] is not None and not p["unlimited"] and not p["diagnostic"]]
        minimum = min((Decimal(p["balance"]) for p in valid), default=Decimal(0))
        maximum = max((Decimal(p["balance"]) for p in valid), default=Decimal(0))
        axis, offset = balance_ticks(minimum, maximum) if valid else ('<span>Unknown</span><span></span><span></span>', None)
        name = "Credit balance · account-wide · right axis · observed range, not zero-based"
        if offset is not None:
            name += f' · Axis offset: +{format(offset, "f")} credits'
        table = balances(points, start, end, timezone) if inspection else ""
        def coordinate(p):
            with localcontext() as context:
                context.prec = max(40, len(minimum.as_tuple().digits) + len(maximum.as_tuple().digits) + 4)
                return height * (1-float((Decimal(p["balance"])-minimum)/(maximum-minimum))) if maximum != minimum else height/2
        def label(p):
            return f'Credit balance · right axis | {p["timestamp"]} | balance {p["balance"]} credits | {p["plan"] or "plan unavailable"}'
        def group(p):
            return "balance",
        def color(p):
            return "var(--text)"
        def summary(p):
            return f'Credit balance · {compact_decimal(p["balance"])} credits'
    latest = {}
    for p in sorted(valid, key=lambda p: datetime.fromisoformat(p["timestamp"]).timestamp()):
        latest[group(p)] = p
    ambiguous_latest = kind == "balance" and latest and len({
        (Decimal(p["balance"]), p["plan"]) for p in valid
        if datetime.fromisoformat(p["timestamp"]) == datetime.fromisoformat(latest[("balance",)]["timestamp"])}) > 1
    key_items = []
    for p in latest.values():
        text = "Credit balance · conflicting latest captures" if ambiguous_latest else summary(p)
        compact_single = compact_key and len(latest) == 1
        if compact_single:
            value = compact_decimal(100-p["used_percent"]) + "%" if kind == "weekly" else compact_decimal(p["balance"]) + " credits"
            text = "Conflicting latest captures" if ambiguous_latest else "Latest: " + value
        detail = "Latest capture is ambiguous" if ambiguous_latest else "Latest captured in selected range | " + name + " | " + label(p)
        swatch = "" if compact_single else f'<i class="ub-account-swatch" style="background:{color(p)}"></i>'
        key_items.append(f'<span tabindex="0" title="{html.escape(detail, quote=True)}" aria-label="{html.escape(detail, quote=True)}">{swatch}{html.escape(text)}</span>')
    key = '<div class="ub-legend ub-meter-legend">' + ''.join(key_items) + '</div>'
    marks = []
    # Preserve exact points. Daily captures are partitioned; no averaging,
    # interpolation or inferred interval debits enter this display layer.
    for p in reduce_points(valid, kind, start, end):
        at = datetime.fromisoformat(p["timestamp"]).timestamp()
        x, y = (at-start)/max(.000001, end-start)*width, coordinate(p)
        title = html.escape(label(p), quote=True)
        last = datetime.fromisoformat(p["timestamp"]) == datetime.fromisoformat(latest[group(p)]["timestamp"])
        marks.append(f'<circle class="ub-account-point" data-boundary="{str(bool(p.get("_boundary"))).lower()}" data-latest="{str(last).lower()}" data-at="{at:.6f}" cx="{x:.3f}" cy="{y:.3f}" r="{2 if last else .65}" fill="{color(p)}" stroke="{color(p)}" role="img" aria-label="{title}"><title>{title}</title></circle>')
    unavailable = f'<p class="ub-note">{kind.title()} overlay unavailable: no supported in-domain captured readings. Original evidence remains inspectable.</p>' if not valid else ""
    conflict_notice = '<p class="ub-note">Conflicting account readings are disclosed in exact inspection, not combined into a weekly meter.</p>' if kind == "weekly" and any(len(v) > 1 for v in signatures.values()) else ""
    mandatory = sum(bool(p.get("_boundary")) for p in valid)
    density = f'<p class="ub-note">Dense boundary evidence: {mandatory:,} captured boundary points are preserved individually, beyond the ordinary display budget.</p>' if mandatory > 720 else ""
    evidence = (f'<details class="ub-overlay-evidence"><summary>Account overlay evidence</summary>{conflict_notice}{density}'
        '<p class="ub-note">Captured points only; no joining or interpolation across gaps, resets or corrections.</p></details>')
    warning = '<p class="ub-note">Conflicting account readings excluded from the overlay.</p>' if conflict_notice else ""
    return CapturedLayer("".join(marks), axis, name, "" if inspection else key,
        table + unavailable + conflict_notice if inspection else unavailable + warning + evidence)
