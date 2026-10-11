"""Immediate script-free HTML hit targets over unchanged SVG usage geometry."""
import html

from codex_usage.report_breakdown_numbers import metric_label


def bucket_hover(context, values, metric, colors, names, *, left, width, top,
                 height, center, href=None, incomplete=False):
    rows = []
    descriptions = []
    for label, value in values.items():
        name = names.get(label, label)
        display = metric_label(value, metric)
        descriptions.append(name + ": " + display)
        rows.append(f'<span class="ub-hover-row"><i style="background:{colors[label]}"></i>'
            f'<span>{html.escape(name)}</span><strong>{html.escape(display)}</strong></span>')
    total_name = "Known total" if incomplete else "Total"
    label = context + " | " + total_name + " " + metric_label(sum(values.values()), metric)
    label += " | " + "; ".join(descriptions)
    if incomplete:
        note = "Unknown estimated credits; not known zero" if metric == "credits" else "Unknown or API-excluded values; not zero"
        label += " | " + note
        rows.append(f'<span class="ub-hover-note">{note}</span>')
    if not rows:
        rows.append('<span class="ub-hover-note">No captured local usage; not proof of zero account workload</span>')
    tag = "a" if href else "span"
    attributes = f' href="{html.escape(href, quote=True)}"' if href else ' role="img"'
    return (f'<span class="ub-hover-bucket" style="--ub-tip-x:{center:.6f}%">'
        f'<{tag} class="ub-hover-target" tabindex="0"{attributes} '
        f'aria-label="{html.escape(("Inspect " if href else "") + label, quote=True)}" '
        f'style="left:clamp(0px,{left:.6f}%,max(0px,calc(100% - max(3px,{width:.6f}%))));'
        f'width:max(3px,{width:.6f}%);top:{top:.6f}px;height:{height:.6f}px">'
        f'<span class="ub-hover-hit" title="" aria-hidden="true"></span></{tag}>'
        '<span class="ub-hover-tooltip" role="tooltip" aria-hidden="true">'
        f'<strong class="ub-hover-time">{html.escape(context)}</strong>'
        f'<span class="ub-hover-total">{total_name} {html.escape(metric_label(sum(values.values()), metric))}</span>'
        + ''.join(rows) + '</span></span>')


def css():
    return """<style>
    .ub-scroll {position:relative}
    .ub-scroll>svg {position:relative;pointer-events:none}
    .ub-scroll .ub-account-point {pointer-events:all}
    .ub-hover-bucket {display:contents}
    .ub-hover-target {position:absolute;min-width:3px;padding:0!important;background:transparent}
    .ub-hover-hit {position:absolute;inset:0}
    .ub-hover-tooltip {position:absolute;top:8px;left:clamp(0px,calc(var(--ub-tip-x) - 130px),max(0px,calc(100% - 260px)));width:260px;max-width:100%;box-sizing:border-box;padding:8px 10px;z-index:8;border-radius:4px;background:var(--tooltip-bg);color:var(--tooltip-text);box-shadow:0 3px 12px rgba(0,0,0,.22);font-size:12px;line-height:17px;opacity:0;visibility:hidden;pointer-events:none;transition:none;overflow-wrap:anywhere}
    .ub-hover-target:hover+.ub-hover-tooltip,.ub-hover-target:focus-visible+.ub-hover-tooltip {opacity:1;visibility:visible}
    .ub-hover-target:focus-visible {outline:2px solid var(--accent);outline-offset:2px}
    .ub-hover-time,.ub-hover-total,.ub-hover-note {display:block}
    .ub-hover-total {margin:3px 0 5px}
    .ub-hover-row {display:grid;grid-template-columns:8px minmax(0,1fr) auto;gap:6px;align-items:baseline;margin-top:3px}
    .ub-hover-row i {width:8px;height:8px}.ub-hover-row strong {white-space:nowrap}
    </style>"""
