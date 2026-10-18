"""Immediate CSS inspection without changing SVG geometry or enabling scripts."""
import html


def tooltip(key, label, x):
    lines = label.splitlines()
    content = f'<strong>{html.escape(lines[0])}</strong>'
    content += ''.join(f'<span>{html.escape(line)}</span>' for line in lines[1:])
    return (f'<span class="speed-tooltip" data-speed-tip-for="{key}" role="tooltip" '
            f'aria-hidden="true" style="--speed-tip-x:{x:.4f}%">{content}</span>'
            '<style>'
            f'.speed-hover-scope:has([data-speed-tip="{key}"]:hover)'
            f'>.speed-tooltip[data-speed-tip-for="{key}"],'
            '.speed-hover-scope:not(:has([data-speed-tip]:hover))'
            f':has([data-speed-tip="{key}"]:focus-visible)'
            f'>.speed-tooltip[data-speed-tip-for="{key}"]'
            '{opacity:1;visibility:visible}</style>')


def css():
    return """
    .speed-hover-scope { position:relative; }
    .speed-tooltip { position:absolute; top:8px;
        left:clamp(0px,calc(var(--speed-tip-x) - 160px),max(0px,calc(100% - 320px)));
        width:320px; max-width:100%; box-sizing:border-box; padding:10px 12px;
        z-index:8; border:1px solid var(--border); border-radius:4px;
        background:var(--tooltip-bg); color:var(--tooltip-text);
        box-shadow:0 3px 12px rgba(0,0,0,.22); font-size:12px; line-height:18px;
        text-align:left; overflow-wrap:anywhere; pointer-events:none;
        opacity:0; visibility:hidden; transition:none; }
    .speed-tooltip strong,.speed-tooltip span { display:block; }
    .speed-tooltip strong { font-weight:650; margin-bottom:2px; }
    """
