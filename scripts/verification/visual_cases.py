"""Independent required visual inventory; counts alone are not qualification."""
from itertools import product

ENGINES = ("chromium", "webkit", "firefox")
THEMES = ("day", "night")
WIDTHS = (1440, 760, 360)
BREAKDOWN_SCENARIOS = (
    "daily-cost-model", "control-metric-tokens-1", "control-group-project-2",
    "control-metric-credits-3", "control-overlay-balance-4", "control-overlay-none-5",
    "control-grain-hourly-6", "control-overlay-weekly-7", "control-metric-cost-8",
    "control-group-model-9", "control-view-project-10", "control-metric-tokens-11",
    "control-metric-credits-12", "control-view-time-13", "control-grain-daily-14",
    "daily-drill", "previous", "hour-drill", "project-drill", "return-daily",
    "empty-filter", "month-selected", "month-empty-filter", "expired-anchor",
    "partial-coverage", "thirty-days", "lord-howe-partial", "dense-history",
    "chatham-partial", "toronto-repeated", "five-hour-only", "missing-duration",
    "multi-weekly", "large-balance-small-decrease", "extreme-balances",
    "tiny-balances", "signed-credit-changes", "large-token-scale",
    "unknown-balances", "unlimited-balances",
)
ALLOWANCE_STATES = (
    "qualified", "previous-window", "stale", "unavailable", "partial",
    "multi-bucket", "insufficient", "credits-stale", "credits-unlimited", "credits-missing",
)
PERIOD_HISTORY_STATES = ("period-history", "period-history-dense")
ASSERTIONS = {
    "breakdown": ("script-disabled", "section-controls-fit", "fixed-visible-axes",
        "axis-glyph-containment", "dated-mark-inspection", "issued-command-links",
        "conditional-account-states", "view-controls", "time-glyph-collision",
        "time-span-containment", "time-alignment", "keyboard-disclosure"),
    "speed": ("script-disabled", "layout-axes-ticks", "series-labels", "marker-bounds",
        "interval-hover-focus", "keyboard-detail-disclosure", "range-empty-states"),
    "overlay": ("script-disabled", "fixed-axes", "time-alignment", "account-axis-key",
        "complete-captured-points", "legend-color", "real-hover", "keyboard-evidence"),
    "hover": ("script-disabled", "compact-time-labels", "empty-native-title",
        "readable-values", "issued-links", "tooltip-containment", "hover-hide-250ms-or-bound-deferral",
        "keyboard-focus-250ms-or-bound-deferral", "tab-order", "account-hit-test"),
    "allowance": ("script-disabled", "content-states", "layout", "keyboard-details",
        "native-meter-semantics", "theme-contrast", "painted-meter-pixels",
        "period-history-local-dst", "uncertain-capture-provenance", "cross-boundary-fit-details",
        "bounded-capture-tables", "period-keyboard-disclosures", "period-theme-layout",
        "period-current-anchor", "official-display-continuity", "all-history-issued-navigation"),
    "screenshots": ("synthetic-private-markers", "no-script-elements", "theme-layout",
        "real-controls-tooltips", "capture-validation"),
    "economics": ("script-disabled", "per-model-metrics", "bounded-display-precision",
        "coverage-priceability-details", "real-keyboard-disclosures", "table-local-scroll",
        "sticky-model-identity", "no-page-overflow", "theme-layout"),
}


def identity(engine, scenario, theme, width, **extra):
    return {"engine": engine, "scenario": scenario, "theme": theme, "width": width, **extra}


def case_key(case):
    required = ("engine", "scenario", "theme", "width")
    if not isinstance(case, dict) or any(key not in case for key in required):
        raise ValueError("Invalid visual case identity")
    if type(case["width"]) is not int or any(not isinstance(case[key], str) or not case[key]
        or "/" in case[key] for key in required[:3]):
        raise ValueError("Invalid visual case field types")
    if "embedded" in case and type(case["embedded"]) is not bool:
        raise ValueError("Invalid embedded case field")
    if "used" in case and type(case["used"]) is not int:
        raise ValueError("Invalid meter case field")
    parts = [str(case[key]) for key in required]
    parts.extend(f"{key}={case[key]}" for key in sorted(set(case) - set(required)))
    return "/".join(parts)


def expected_cases(suite):
    if suite == "breakdown":
        scenarios = BREAKDOWN_SCENARIOS
    elif suite == "overlay":
        scenarios = ("dense-weekly", "multi-weekly", "credit-balance", "weekly-full", "weekly-empty")
    elif suite == "hover":
        scenarios = ("single-day", "multi-day", "dst", "tokens")
    elif suite == "speed":
        cases = [identity(e, s, t, w, embedded=embedded)
            for e, s, t, (w, embedded) in product(ENGINES,
                ("daily", "daily-all", "hourly", "empty-week", "single-day", "daily-single"),
                THEMES, ((1440, False), (760, False), (360, False), (1440, True)))]
        return cases + [identity(e, "converging", t, w) for e, t, w in product(ENGINES, THEMES, WIDTHS)]
    elif suite == "allowance":
        cases = [identity(e, s, t, w) for e, s, t, w in product(ENGINES,
            ALLOWANCE_STATES + PERIOD_HISTORY_STATES, THEMES, WIDTHS)]
        return cases + [identity(e, "meter", t, 360, used=used)
            for e, t, used in product(ENGINES, (*THEMES, "vscode"), (0, 17, 83, 100))]
    elif suite == "screenshots":
        cases = [identity("chromium", s, t, w)
            for s, t, w in product(("usage", "storage"), THEMES, (1440, 760))]
        cases += [identity("chromium", "speed", t, 1440) for t in THEMES]
        cases += [identity("pillow", "image-usage", t, w) for t, w in product(THEMES, (1440, 760))]
        return cases + [identity("pillow", "image-storage", "night", 1440)]
    elif suite == "economics":
        scenarios = ("within-project-model-comparison",)
    else:
        raise ValueError(f"Unknown visual suite: {suite}")
    return [identity(e, s, t, w) for e, s, t, w in product(ENGINES, scenarios, THEMES, WIDTHS)]


def validate_inventory(evidence, suite):
    if type(evidence.get("schema")) is not int or evidence["schema"] != (2 if suite == "hover" else 1) or evidence.get("suite") != suite:
        raise ValueError("Unknown or foreign visual evidence contract")
    if evidence.get("status") != ("functional-complete" if suite == "hover" else "passed") or evidence.get("synthetic_only") is not True:
        raise ValueError("Visual evidence is incomplete, failed or private")
    if evidence.get("assertions") != list(ASSERTIONS[suite]):
        raise ValueError("Visual assertion inventory differs")
    actual = [case_key(case) for case in evidence.get("completed", [])]
    expected = {case_key(case) for case in expected_cases(suite)}
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError(f"Visual case mismatch: missing={sorted(expected-set(actual))[:5]}, "
            f"unexpected={sorted(set(actual)-expected)[:5]}, duplicates={len(actual)-len(set(actual))}")
