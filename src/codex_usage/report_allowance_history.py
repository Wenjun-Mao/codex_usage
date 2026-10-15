"""Bounded period-first presentation of captures and unchanged monetary fits."""
from datetime import datetime

from codex_usage.allowance_display_history import SUPPORTED


PERIOD_LIMIT = 12
CAPTURE_LIMIT = 100
FIT_LIMIT = 12


def period_history(report, timezone):
    from codex_usage.report_allowance import _local_reset, series_label, text

    history = report["display_history"]
    captures = history["captures"]

    def observed(fragment):
        indices = fragment["capture_indices"]
        dates = [datetime.fromisoformat(captures[i]["timestamp"]).astimezone(timezone).date()
                 for i in (indices[0], indices[-1])]
        return f"Observed {dates[0]} to {dates[1]}"

    def fragment_html(fragment):
        reset = fragment["next_reset"]
        next_reset = ""
        if reset is not None and not fragment["uncertain"] and not fragment["ended_by"]:
            iso, label = _local_reset(reset, timezone)
            next_reset = f' · Next reset <time datetime="{text(iso)}">{text(label)}</time>'
        status = ("Uncertain" if fragment["uncertain"] else
                  "Current" if fragment["current"] else
                  "Ended" if fragment["ended_by"] in SUPPORTED | {"plan change"} else
                  "Coverage ended" if fragment["ended_by"] else "Last observed")
        return (
            '<li class="allowance-history-item">'
            f'<div class="allowance-history-heading"><span class="allowance-history-series">{series_label(fragment)}</span>'
            f'<strong>{status}</strong></div>'
            f'<p class="allowance-history-meta">{text(observed(fragment))}{next_reset}</p>'
            f'<details><summary>Capture details ({len(fragment["capture_indices"])}) · '
            f'Fits ({len(fragment["fit_indices"])})</summary>'
            f'<p>Boundary: {text(fragment["boundary"])} · '
            f'End: {text(fragment["ended_by"] or "not observed")}. Actual start not established.</p>'
            f'{_captures(history, fragment["capture_indices"], timezone)}'
            f'{_fits(report, fragment["fit_indices"], timezone)}</details></li>'
        )

    periods = history["periods"]
    uncertain = history["uncertain"]
    cross = history["cross_boundary_fit_indices"]
    items = "".join(fragment_html(fragment) for fragment in periods[:PERIOD_LIMIT])
    uncertain_markup = ""
    if uncertain or cross:
        count = sum(len(fragment["capture_indices"]) for fragment in uncertain)
        uncertain_markup = (
            f'<details class="allowance-uncertain"><summary>Uncertain readings ({count})</summary>'
            f'<p>{len(uncertain)} fragments; newest {min(PERIOD_LIMIT, len(uncertain))} shown. '
            f'{len(cross)} cross-boundary fits retained separately.</p>'
            '<ol class="allowance-history">'
            + "".join(fragment_html(fragment) for fragment in uncertain[:PERIOD_LIMIT])
            + '</ol>'
            + (f'<details><summary>Uncertain / cross-boundary fits ({len(cross)})</summary>'
               f'{_fits(report, cross, timezone)}</details>' if cross else "")
            + '</details>'
        )
    return (
        '<h3>Allowance history</h3>'
        f'<p class="allowance-history-count">{len(periods)} observed periods; '
        f'newest {min(PERIOD_LIMIT, len(periods))} shown. {len(captures)} exact captures. '
        'Observed coverage is not the subscription start.</p>'
        f'<ol class="allowance-history" aria-label="Allowance period history">{items}</ol>'
        f'{uncertain_markup}'
    )


def _captures(history, indices, timezone):
    from codex_usage.report_allowance import _observation_row, _SOURCE_DESCRIPTION, text

    selected = indices[-CAPTURE_LIMIT:]
    rows = "".join(_observation_row(history["captures"][index], timezone, full=True) for index in selected)
    return (
        f'<p>Most recent {len(selected)} of {len(indices)} exact captures shown.</p>'
        '<div class="table-scroll" tabindex="0" role="region" aria-label="Quota observations">'
        '<table class="allowance-observations"><thead><tr><th>Observed at</th><th>Used</th>'
        f'<th title="{text(_SOURCE_DESCRIPTION)}">Slot · Source</th><th>Reset</th>'
        '<th>Plan</th><th>Duration (min)</th><th>Reset credits</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div>'
    )


def _fits(report, indices, timezone):
    from codex_usage.report_allowance import estimate_number, money, text, _local_observation

    items = []
    for index in reversed(indices[-FIT_LIMIT:]):
        window = report["windows"][index]
        estimate = window["estimate"]
        _, start = _local_observation(window["start"], timezone, detailed=True)
        _, end = _local_observation(window["end"], timezone, detailed=True)
        excluded = window.get("excluded_observations", 0)
        items.append(
            f'<details class="allowance-fit"><summary>Fit {index + 1} · {text(estimate["confidence"])} · '
            f'{money(estimate["value"])}</summary>'
            f'<p>Observed {text(start)} to {text(end)} · {text(window["closure"])}</p>'
            f'<p>{estimate_number(estimate["span"])} percentage points · {estimate["bins"]} bins · '
            f'local cost span {money(estimate["cost_span"])}</p>'
            f'<p>R² {estimate["r_squared"]:.3f} · sensitivity P90/P10 '
            f'{estimate_number(estimate["sensitivity_ratio"])} · {window["corrections"]} meter corrections · '
            f'{len(window["points"])} fit-window captures · {excluded} excluded from first reported-full onward.</p>'
            f'<p>{"100% priced" if window.get("fully_priced", True) else "Unpriced usage: monetary estimate unavailable"} · '
            f'{"Complete local ledger" if window.get("coverage_complete", True) else "Partial local ledger"}</p></details>'
        )
    return f'<p>{len(indices)} independent fits; newest {len(items)} shown.</p>' + "".join(items)
