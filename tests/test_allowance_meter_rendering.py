from codex_usage.report_allowance import allowance_css, render_allowance_section


def test_active_bucket_meter_represents_remaining_allowance_and_keeps_theme_styling():
    report = {
        "status": {
            "plan": "pro",
            "active_buckets": [
                {
                    "limit_id": "codex",
                    "duration_minutes": 10080,
                    "used_percent": 17,
                    "resets_at": None,
                }
            ],
            "probe_status": "fresh",
            "last_probe_at": None,
            "lifetime_tokens": None,
            "recovery": {"complete": 0, "pending": 0, "unavailable": 0},
        },
        "windows": [],
        "qualified": [],
        "headline": None,
        "headline_previous": False,
        "history": [],
    }
    markup = render_allowance_section(report)
    css = allowance_css()

    assert 'value="83"' in markup
    assert 'aria-label="codex · 7 days percentage remaining"' in markup
    assert 'aria-valuetext="83% remaining"' in markup
    assert "17% used · 83% remaining" in markup
    assert 'role="progressbar"' not in markup and 'role="meter"' not in markup
    assert "appearance: none" in css
    assert "::-webkit-meter-optimum-value" in css
    assert "::-webkit-meter-suboptimum-value" in css
    assert "::-webkit-meter-even-less-good-value" in css
    assert "::-moz-meter-bar" in css
    assert "background: var(--accent, var(--astra" in css
    assert "background: var(--surface-soft, var(--soft" in css
    assert ".plan-allowance summary:focus-visible" in css
