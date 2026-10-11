"""Axis-linked keys for additive usage and independent captured account readings."""
import html


def axis_linked_chart(*, metric, title, scale, usage_marks, layer, grid,
                      timeline, labels, width, height, kind, hover_targets=""):
    usage_title = {"tokens": "Tokens", "cost": "API-equivalent cost ($)",
                   "credits": "Estimated Standard credits"}[metric]
    usage_key = '<div class="ub-legend">' + ''.join(
        f'<span><i style="background:{color}"></i>{html.escape(label)}</span>'
        for label, color in labels) + '</div>'
    swatches = ''.join(f'<i style="background:{color}"></i>' for _, color in labels[:3])
    usage_heading = (f'<div class="ub-linked-heading ub-usage-heading">'
        f'<div class="ub-linked-axis-name"><span class="ub-bar-key" aria-hidden="true">{swatches}</span>'
        f'<strong>{usage_title}</strong></div>'
        f'<div class="ub-note">{html.escape(title)} &middot; selected projects</div>{usage_key}</div>')
    account_title = "Allowance Remaining" if kind == "weekly" else "Credit Balance"
    account_heading = (f'<div class="ub-linked-heading ub-account-heading">'
        f'<div class="ub-linked-axis-name ub-account-title" title="{html.escape(layer.name, quote=True)}"><i class="ub-dot-key" aria-hidden="true"></i>'
        f'<strong>{account_title}</strong></div>'
        + layer.key + '</div>')
    content = '<div class="ub-axis-linked" data-layout="axis-linked">'
    content += '<div class="ub-linked-head">' + usage_heading + (account_heading if layer.axis else "") + '</div>'
    # WebKit clips hit testing at SVG edges, even with visible paint overflow.
    # Extend the viewport symmetrically without moving the timeline transform.
    marker_room = 4 if layer.axis else 0
    content += (f'<div class="ub-chart{" ub-shared" if layer.axis else ""}" style="--ub-axis-height:{height}px">'
        f'<div class="ub-axis">{scale}</div><div class="ub-scroll">' + hover_targets +
        f'<svg width="100%" height="{height+8}" viewBox="{-marker_room} -4 {width+2*marker_room} {height+8}" preserveAspectRatio="none"'
        f' style="width:{100*(width+2*marker_room)/width:.6f}%;margin-left:{-100*marker_room/width:.6f}%"'
        f' role="img" aria-label="{html.escape(usage_title + ("; " + layer.name if layer.axis else ""), quote=True)}">'
        + grid + usage_marks + layer.marks + '</svg>' + timeline + '</div>'
        + (f'<div class="ub-axis ub-right-axis">{layer.axis}</div>' if layer.axis else "") + '</div>')
    if kind == "balance" and layer.axis:
        content += f'<p class="ub-note">{html.escape(layer.name)}</p>'
    return css() + content + layer.evidence + '</div>'


def css():
    return """<style>
    .ub-axis-linked {min-width:0;margin-top:14px}
    .ub-linked-head {display:grid;gap:18px;grid-template-columns:minmax(0,1fr) minmax(0,1fr)}
    .ub-linked-heading {min-width:0}
    .ub-linked-axis-name {display:flex;align-items:flex-start;gap:7px;font-size:13px;line-height:18px;margin-bottom:3px}
    .ub-linked-axis-name strong {font-weight:650;overflow-wrap:anywhere}
    .ub-bar-key {display:flex;flex-direction:column;width:10px;height:14px;flex-shrink:0;margin-top:2px}
    .ub-bar-key i {display:block;flex:1;min-height:3px}
    .ub-dot-key {display:block;width:7px;height:7px;border-radius:50%;background:var(--text);flex-shrink:0;margin-top:6px}
    .ub-account-heading {text-align:right}
    .ub-account-heading .ub-linked-axis-name,.ub-account-heading .ub-meter-legend {justify-content:flex-end}
    .ub-account-heading .ub-meter-legend {margin:8px 0}
    .ub-account-heading .ub-meter-legend span:focus-visible {outline:2px solid var(--accent);outline-offset:3px}
    /* Match tick centers to the plot plus SVG marker room and wrapper padding. */
    .ub-axis-linked .ub-axis {height:calc(var(--ub-axis-height,180px) + 14px)}
    .ub-linked-head:not(:has(.ub-account-heading)) {grid-template-columns:minmax(0,1fr)}
    @media(max-width:560px) {.ub-linked-head {gap:14px}}
    </style>"""
