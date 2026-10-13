"""Each old layout invariant still rejects a broken snapshot."""
from copy import deepcopy

import pytest

from release_tooling_support import load_tool

assert_layout = load_tool("verification.breakdown_layout").assert_layout


def valid_snapshot():
    box = {"textLeft": 0, "textRight": 10, "spanLeft": 0, "spanRight": 10,
        "gutterLeft": 0, "gutterRight": 10}
    return {"sections": 1, "scripts": 0, "sectionFits": True, "controlsFit": True,
        "axes": [{"visible": True, "font": "12px", "boxes": [box]}],
        "titlesDated": 2, "titleCount": 2, "linksDated": 2, "linkCount": 2,
        "linksIssued": True, "svg": 1, "windowPickers": 1, "rightAxes": 0,
        "oldContext": False, "timeAxes": [{"font": "12px", "rect": {"left": 0, "right": 100},
            "ticks": [{"glyph": {"left": 0, "right": 20}, "span": {"left": 0, "right": 20}, "error": 0},
                {"glyph": {"left": 80, "right": 100}, "span": {"left": 80, "right": 100}, "error": 0}]}]}


@pytest.mark.parametrize("fault", ["scripts", "sections", "sectionFits", "controlsFit",
    "axis-hidden", "axis-font", "axis-glyph", "titlesDated", "linksDated", "linksIssued",
    "linkCount", "svg", "windowPickers", "oldContext", "tick-font", "glyph-overlap",
    "span-overflow", "alignment"])
def test_original_invariants_remain_sensitive(fault):
    sample = valid_snapshot()
    state = {"view": "time", "overlay": "none"}
    assert_layout(sample, "fixture", state)
    if fault in ("scripts", "sections", "svg", "titlesDated", "linksDated", "linkCount", "windowPickers"):
        sample[fault] += 1 if fault in ("scripts", "sections", "svg") else -1 if fault != "linkCount" else -2
    elif fault in ("sectionFits", "controlsFit", "linksIssued", "oldContext"):
        sample[fault] = not sample[fault]
    elif fault.startswith("axis-"):
        axis = sample["axes"][0]
        if fault == "axis-hidden":
            axis["visible"] = False
        elif fault == "axis-font":
            axis["font"] = "11px"
        else:
            axis["boxes"][0]["textRight"] = 12
    else:
        axis = sample["timeAxes"][0]
        if fault == "tick-font":
            axis["font"] = "11px"
        elif fault == "glyph-overlap":
            axis["ticks"][1]["glyph"]["left"] = 10
        elif fault == "span-overflow":
            axis["ticks"][1]["span"]["right"] = 102
        else:
            axis["ticks"][0]["error"] = 2
    with pytest.raises(AssertionError):
        assert_layout(sample, "fixture", state)


def test_account_and_project_conditional_contracts():
    sample = valid_snapshot()
    state = {"view": "time", "overlay": "none"}
    sample.update(rightText="Unknown", finiteMissing=True, capturesMissing=False)
    assert_layout(sample, "unknown-balances", state)
    broken = deepcopy(sample)
    broken["capturesMissing"] = True
    with pytest.raises(AssertionError):
        assert_layout(broken, "unknown-balances", state)
    sample.update(legend="another-limit · weekly · plus; codex · weekly · pro")
    assert_layout(sample, "multi-weekly", state)
    sample["legend"] = "codex · weekly · pro"
    with pytest.raises(AssertionError):
        assert_layout(sample, "multi-weekly", state)
    sample.update(svg=0, windowPickers=0, timeAxes=[], rightAxes=0)
    assert_layout(sample, "project", {"view": "project", "overlay": "none"})
    sample["rightAxes"] = 1
    with pytest.raises(AssertionError):
        assert_layout(sample, "project", {"view": "project", "overlay": "none"})
