"""Only the named additive presentation contract may differ from the old oracle."""
from copy import deepcopy

import pytest

from release_tooling_support import load_tool

assert_frozen_parity = load_tool("check_speed_parity").assert_frozen_parity


def snapshot():
    return {"allowance": {"headline": {"value": 12.34}, "windows": [{"cost": 5.6}]},
            "records": [1], "monetary": {"cost": 7.8}, "image_facts": [2], "repo_candidates": [3]}


def presentation():
    return {"captures": [], "periods": [], "uncertain": [], "cross_boundary_fit_indices": []}


def test_old_financial_oracle_allows_only_the_explicit_additive_display_contract():
    expected = snapshot()
    candidate = deepcopy(expected)
    candidate["allowance"]["display_history"] = presentation()
    unchanged = deepcopy((expected, candidate))
    assert assert_frozen_parity(expected, candidate) == ["allowance.display_history"]
    assert (expected, candidate) == unchanged
    assert assert_frozen_parity(expected, deepcopy(expected)) == []


@pytest.mark.parametrize("section", ["allowance", "records", "monetary", "image_facts", "repo_candidates"])
def test_changed_original_facts_are_rejected_even_with_an_added_display_contract(section):
    expected = snapshot()
    candidate = deepcopy(expected)
    candidate["allowance"]["display_history"] = presentation()
    if section == "allowance":
        candidate[section]["headline"]["value"] += 0.01
    elif isinstance(candidate[section], dict):
        candidate[section]["cost"] += 0.01
    else:
        candidate[section].append(99)
    with pytest.raises(AssertionError, match="changed frozen evidence"):
        assert_frozen_parity(expected, candidate)


@pytest.mark.parametrize("section", ["allowance", "snapshot"])
def test_unexpected_additive_fields_are_not_silently_ignored(section):
    expected = snapshot()
    candidate = deepcopy(expected)
    candidate["allowance"]["display_history"] = presentation()
    (candidate["allowance"] if section == "allowance" else candidate)["unexpected"] = []
    with pytest.raises(AssertionError, match="changed frozen evidence"):
        assert_frozen_parity(expected, candidate)


@pytest.mark.parametrize("history", [None, {}, {**presentation(), "periods": None},
                                     {**presentation(), "unexpected": []}])
def test_malformed_additive_display_contract_is_rejected(history):
    expected = snapshot()
    candidate = deepcopy(expected)
    candidate["allowance"]["display_history"] = history
    with pytest.raises(AssertionError, match="invalid additive"):
        assert_frozen_parity(expected, candidate)


@pytest.mark.parametrize("remove", [False, True])
def test_an_oracle_that_already_contains_display_history_remains_fully_strict(remove):
    expected = snapshot()
    expected["allowance"]["display_history"] = presentation()
    candidate = deepcopy(expected)
    assert assert_frozen_parity(expected, candidate) == []
    if remove:
        candidate["allowance"].pop("display_history")
    else:
        candidate["allowance"]["display_history"]["periods"].append({"current": True})
    with pytest.raises(AssertionError, match="changed frozen evidence"):
        assert_frozen_parity(expected, candidate)


def test_additive_reset_history_is_reference_validated_and_existing_oracle_stays_strict(tmp_path):
    report = load_tool("allowance_period_fixture").reset_economics_fixture(tmp_path)
    candidate = {"allowance": report}
    expected = deepcopy(candidate)
    expected["allowance"].pop("reset_history")
    assert assert_frozen_parity(expected, candidate) == ["allowance.reset_history"]
    invalid = deepcopy(candidate)
    invalid["allowance"]["reset_history"]["periods"][0]["usage_usd"] = float("nan")
    with pytest.raises(AssertionError, match="invalid additive"):
        assert_frozen_parity(expected, invalid)
    with pytest.raises(AssertionError, match="changed frozen"):
        assert_frozen_parity(candidate, invalid)
