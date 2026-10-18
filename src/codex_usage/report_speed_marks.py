"""Shared fixed-size speed markers and compact, unambiguous model labels."""
import html
import re
from datetime import date, datetime

from codex_usage.report_calendar import calendar_label


MARKERS = (
    '<rect x="-4" y="-4" width="8" height="8"/>',
    '<circle cx="0" cy="0" r="4"/>',
    '<path d="M0 -5 5 0 0 5 -5 0Z"/>',
    '<path d="M-5 -3 5 -3 0 5Z"/>',
    '<path d="M0 -5 4 -2 3 4 -3 4 -4 -2Z"/>',
    '<path d="M0 -5 5 4 -5 4Z"/>',
    '<circle cx="0" cy="0" r="4"/>',
)


def marker(slot, x, y):
    # Direct primitives avoid SVG use-instance hover differences across engines.
    return (f'<g class="speed-marker" data-model-slot="{slot}" '
            f'style="transform:translate({x:.4f}%,{y:.2f}px);transform-box:view-box">'
            f'{MARKERS[slot]}</g>')


def legend_marker(slot):
    return (f'<svg viewBox="-6 -6 12 12" width="12" height="12" aria-hidden="true" '
            f'style="color:var(--model-{slot})">{MARKERS[slot]}</svg>')


def short_model_label(model):
    match = re.fullmatch(r'gpt-(\d+(?:\.\d+)*)-(astra|sol|terra|luna)', model)
    return f'{match[2].title()} {match[1]}' if match else model


def bucket_label(bucket):
    return calendar_label(datetime.fromisoformat(bucket) if "T" in bucket else date.fromisoformat(bucket))


def series_labels(endpoints, slots, *, top, span):
    if not endpoints:
        return ''
    ordered = sorted(endpoints, key=lambda point: (point['y'], point['model']))
    positions = []
    for point in ordered:
        positions.append(max(point['y'] - 14, positions[-1] + 28 if positions else top))
    # Keep labels separate even when model medians converge near the same speed.
    for index in range(len(positions) - 1, -1, -1):
        ceiling = positions[index + 1] - 28 if index + 1 < len(positions) else top + span - 28
        positions[index] = min(positions[index], ceiling)
    labels = []
    for point, y in zip(ordered, positions):
        model = point['model']
        key = f'series-{endpoints.index(point)}'
        labels.append(
            f'<span class="speed-series-label" style="top:{y:.2f}px;'
            f'color:var(--model-{slots[model]})" data-speed-tip="{key}">'
            f'<strong>{html.escape(short_model_label(model))}</strong>'
            f'<small>{point["median"]:.1f} tok/s</small></span>'
        )
    crowded = len(endpoints) > 7 or any(len(short_model_label(point['model'])) > 11 for point in endpoints)
    css_class = 'speed-series-labels speed-series-list' if crowded else 'speed-series-labels'
    return f'<div class="{css_class}" aria-label="Latest measured speed by model">' + ''.join(labels) + '</div>'
