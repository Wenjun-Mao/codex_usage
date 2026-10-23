"""Counts cannot substitute for passing every collected and preserved test case."""
import json
from xml.etree import ElementTree

import pytest

from qualification_fixture import FixtureAPI, policy
from release_tooling_support import load_tool

validator = load_tool("verification.test_inventory")


@pytest.mark.parametrize("complete", [pytest.param(True, id="complete"),
                                     pytest.param(False, id="missing-required")])
def test_local_inventory_command_requires_the_same_complete_cases(tmp_path, capsys, complete):
    files = FixtureAPI().gate_files("core")
    if not complete:
        xml = ElementTree.fromstring(files["tests.xml"])
        first = xml[0]
        xml.remove(first)
        inventory = json.loads(files["inventory.json"])
        inventory["collected"].remove([first.get("classname"), first.get("name")])
        files["tests.xml"] = ElementTree.tostring(xml)
        files["inventory.json"] = policy.canonical(inventory)
    for name in ("tests.xml", "inventory.json"):
        (tmp_path / name).write_bytes(files[name])
    if complete:
        assert validator.main([str(tmp_path)]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result == {"status": "local-test-inventory-only", "skipped": 0,
                          "passed": len(json.loads(files["inventory.json"])["collected"])}
    else:
        with pytest.raises(ValueError, match="Required preserved test cases missing"):
            validator.main([str(tmp_path)])
        assert not capsys.readouterr().out


@pytest.mark.parametrize("fault", ["duplicate", "missing", "uncollected", "collection-duplicate", "unknown-skip",
    "windows-skip", "failure", "error", "exit", "collection-missing", "skip-type", "xml-totals"])
def test_python_collection_and_case_results_are_complete_and_passing(fault):
    files = FixtureAPI().gate_files("core")
    validator.validate_python(files, "core")
    xml = ElementTree.fromstring(files["tests.xml"])
    inventory = json.loads(files["inventory.json"])
    first = xml[0]
    if fault == "duplicate":
        xml.append(ElementTree.fromstring(ElementTree.tostring(first)))
    elif fault == "missing":
        xml.remove(first)
        inventory["collected"].remove([first.get("classname"), first.get("name")])
    elif fault == "uncollected":
        inventory["collected"].pop()
    elif fault == "collection-duplicate":
        inventory["collected"].append(inventory["collected"][0])
    elif fault in ("unknown-skip", "windows-skip"):
        if fault == "windows-skip":
            inventory["platform"] = "Windows"
        ElementTree.SubElement(first, "skipped", type="pytest.skip", message="native junctions are Windows-only")
    elif fault in ("failure", "error"):
        ElementTree.SubElement(first, fault)
    elif fault == "exit":
        inventory["exitstatus"] = 1
    elif fault == "skip-type":
        ElementTree.SubElement(first, "skipped", type="pytest.xfail", message="native junctions are Windows-only")
    elif fault == "xml-totals":
        xml.set("tests", "1")
    else:
        files.pop("inventory.json")
    files["tests.xml"] = ElementTree.tostring(xml)
    if fault != "collection-missing":
        files["inventory.json"] = policy.canonical(inventory)
    with pytest.raises(ValueError):
        validator.validate_python(files, "core")


def test_no_python_skips_are_allowed_after_transfer_retirement():
    files = FixtureAPI().gate_files("core")
    xml = ElementTree.fromstring(files["tests.xml"])
    target = xml[0]
    ElementTree.SubElement(target, "skipped", type="pytest.skip", message="native junctions are Windows-only")
    files["tests.xml"] = ElementTree.tostring(xml)
    with pytest.raises(ValueError, match="Unapproved skipped"):
        validator.validate_python(files, "core")


def test_named_surviving_python_case_cannot_be_removed_with_consistent_counts():
    files = FixtureAPI().gate_files("core")
    xml = ElementTree.fromstring(files["tests.xml"])
    inventory = json.loads(files["inventory.json"])
    name = "test_lane_can_promote_a_coalesced_capture_ahead_of_lower_priority_work"
    target = next(case for case in xml if case.get("name") == name)
    identity = [target.get("classname"), name]
    xml.remove(target)
    inventory["collected"].remove(identity)
    files["tests.xml"] = ElementTree.tostring(xml)
    files["inventory.json"] = policy.canonical(inventory)
    with pytest.raises(ValueError, match="Required preserved test cases missing"):
        validator.validate_python(files, "core")


def test_named_surviving_extension_case_cannot_be_removed_with_consistent_counts():
    files = FixtureAPI().gate_files("package-darwin-arm64")
    name = "usage report receives companion controls and restrictive CSP"
    xml = ElementTree.fromstring(files["extension-tests.xml"])
    xml.remove(next(case for case in xml if case.get("name") == name))
    inventory = json.loads(files["extension-inventory.json"])
    inventory["collected"] = [case for case in inventory["collected"] if case[1] != name]
    inventory["cases"] = [case for case in inventory["cases"] if case["identity"][1] != name]
    for key in ("tests", "passed"):
        inventory["summaries"][0]["counts"][key] -= 1
    files["extension-tests.xml"] = ElementTree.tostring(xml)
    files["extension-inventory.json"] = policy.canonical(inventory)
    with pytest.raises(ValueError, match="Missing, duplicated, skipped or failed extension cases"):
        validator.validate_extension(files)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "skipped", "failure", "error"])
def test_extension_inventory_preserves_every_named_case(fault):
    files = FixtureAPI().gate_files("package-darwin-arm64")
    assert set(validator.validate_extension(files)["passed"]) == set(json.loads(
        (policy.ROOT / "scripts/verification/extension-case-baseline.json").read_text())["required"])
    xml = ElementTree.fromstring(files["extension-tests.xml"])
    if fault == "missing":
        xml.remove(xml[0])
    elif fault == "duplicate":
        xml.append(ElementTree.fromstring(ElementTree.tostring(xml[0])))
    else:
        ElementTree.SubElement(xml[0], fault)
    files["extension-tests.xml"] = ElementTree.tostring(xml)
    with pytest.raises(ValueError):
        validator.validate_extension(files)


@pytest.mark.parametrize("fault", ["incomplete", "failed-summary", "todo", "cancelled", "count", "uncollected", "duplicate", "case-todo", "missing"])
def test_extension_completion_and_all_test_events_are_required(fault):
    files = FixtureAPI().gate_files("package-darwin-arm64")
    inventory = json.loads(files["extension-inventory.json"])
    if fault == "incomplete":
        inventory["complete"] = False
    elif fault == "failed-summary":
        inventory["summaries"][0]["success"] = False
    elif fault in ("todo", "cancelled", "count"):
        inventory["summaries"][0]["counts"]["tests" if fault == "count" else fault] = 1
    elif fault == "uncollected":
        inventory["collected"].pop()
    elif fault == "duplicate":
        inventory["cases"].append(inventory["cases"][0])
    elif fault == "case-todo":
        inventory["cases"][0]["todo"] = True
    files["extension-inventory.json"] = policy.canonical(inventory)
    if fault == "missing":
        files.pop("extension-inventory.json")
    with pytest.raises(ValueError):
        validator.validate_extension(files)
