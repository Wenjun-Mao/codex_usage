"""Literal release compatibility pins: coordinated renderer drift must fail too."""
import re
from unittest.mock import patch

from codex_usage import model_presentation as identity
from codex_usage.report_breakdown_theme import report_breakdown_css
from codex_usage.report_speed_marks import MARKERS


# 2.13.5 speed/project baseline. Editing these is an intentional design change,
# not a normal consequence of adding a model, chart, theme consumer, or palette.
BASELINE = {
    'gpt-6-astra': (0, '#087f8c', '#45c5d6', '<rect x="-4" y="-4" width="8" height="8"/>'),
    'gpt-5.6-sol': (1, '#c47f00', '#f2b84b', '<circle cx="0" cy="0" r="4"/>'),
    'gpt-5.6-terra': (2, '#2e8b57', '#5fc98a', '<path d="M0 -5 5 0 0 5 -5 0Z"/>'),
    'gpt-5.6-luna': (3, '#7656c7', '#b59af1', '<path d="M-5 -3 5 -3 0 5Z"/>'),
    'gpt-6-sol': (4, '#3568c8', '#6f9cf4', '<path d="M0 -5 4 -2 3 4 -3 4 -4 -2Z"/>'),
    'gpt-6-luna': (5, '#bb477d', '#ee7aaa', '<path d="M0 -5 5 4 -5 4Z"/>'),
    'gpt-6.1-sol': (6, '#c74f37', '#ef806b', '<circle cx="0" cy="0" r="4"/>'),
    'gpt-6.1-terra': (8, '#727327', '#c6c76a', '<path d="M-5 0 -2.5 -4.3 2.5 -4.3 5 0 2.5 4.3 -2.5 4.3Z"/>'),
}


# Current deterministic identities for real names previously using fallback.
# Explicit registration must preserve these too, unless design migration is
# intentional; checking only synthetic names would miss that promotion drift.
HISTORICAL_FALLBACK = {
    'codex-auto-review': (8, '<path d="M-5 0 -2.5 -4.3 2.5 -4.3 5 0 2.5 4.3 -2.5 4.3Z"/>'),
    'gpt-5.5': (6, '<circle cx="0" cy="0" r="4"/>'),
    'gpt-5.4': (2, '<path d="M0 -5 5 0 0 5 -5 0Z"/>'),
    'gpt-5.3-codex-spark': (5, '<path d="M0 -5 5 4 -5 4Z"/>'),
}


def test_historical_fallback_names_keep_identity_after_explicit_registration():
    for model, (slot, shape) in HISTORICAL_FALLBACK.items():
        assert identity.model_color_slot(model) == slot
        assert identity.model_color_slot(model.upper()) == slot
        assert MARKERS[slot] == shape


def test_exact_released_colors_and_marker_geometry_remain_stable():
    css = report_breakdown_css()
    day = css.split(':root {', 1)[1].split('}', 1)[0]
    night = css.split('html[data-codex-theme="night"] {', 1)[1].split('}', 1)[0]
    for model, (slot, light, dark, shape) in BASELINE.items():
        assert identity.model_color_slot(model) == slot
        assert f'--model-{slot}: {light};' in day
        assert f'--model-{slot}: {dark};' in night
        assert MARKERS[slot] == shape
        assert f'.model-color-slot-{slot} {{ background: var(--model-{slot}); }}' in css
    assert '--model-7: #8b949f;' in day and '--model-7: #a5adb8;' in night
    assert 7 not in identity.assign_model_color_slots(tuple(BASELINE)).values()


def test_fallback_is_frozen_when_known_registry_and_palette_expand():
    unknowns = ('custom-one', 'custom-two', 'custom-three', 'GPT-FUTURE', 'custom-<unsafe>"&')
    # Literal assignments pin digest algorithm, case normalization, and domain.
    expected = {'custom-one': 1, 'custom-two': 6, 'custom-three': 1,
                'GPT-FUTURE': 8, 'custom-<unsafe>"&': 6}
    assert identity.assign_model_color_slots(unknowns) == expected
    with patch.dict(identity._STABLE_COLOR_SLOTS, {'new-known-model': 9}), \
         patch.object(identity, 'MODEL_COLOR_SLOTS', (*identity.MODEL_COLOR_SLOTS, 9, 10)):
        assert identity.assign_model_color_slots(unknowns) == expected
        for model, (slot, *_rest) in BASELINE.items():
            assert identity.model_color_slot(model) == slot


def test_all_slots_resolve_in_high_contrast_and_forced_color_themes():
    css = report_breakdown_css()
    forced = css.split('@media (forced-colors: active)', 1)[1].split('}', 1)[0]
    high = css.split('body.vscode-high-contrast {', 1)[1].split('}', 1)[0]
    for slot in (*identity.MODEL_COLOR_SLOTS, 7):
        assert re.search(rf'--model-{slot}: (?:CanvasText|GrayText);', forced)
        assert f'--model-{slot}: var(--text);' in high
