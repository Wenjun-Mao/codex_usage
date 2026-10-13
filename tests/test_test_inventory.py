"""Counts cannot substitute for passing every collected and preserved test case."""
import json
from xml.etree import ElementTree

import pytest

from qualification_fixture import FixtureAPI, policy
from release_tooling_support import load_tool

validator = load_tool("verification.test_inventory")


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
            first = next(test for test in xml if (test.get("classname"), test.get("name")) == validator.ALLOWED_SKIP)
            inventory["platform"] = "Windows"
        ElementTree.SubElement(first, "skipped", type="pytest.skip", message="native junctions are Windows-only")
    elif fault in ("failure", "error"):
        ElementTree.SubElement(first, fault)
    elif fault == "exit":
        inventory["exitstatus"] = 1
    elif fault == "skip-type":
        first = next(test for test in xml if (test.get("classname"), test.get("name")) == validator.ALLOWED_SKIP)
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


def test_only_named_native_windows_junction_skip_is_allowed_off_windows():
    files = FixtureAPI().gate_files("core")
    xml = ElementTree.fromstring(files["tests.xml"])
    target = next(test for test in xml if (test.get("classname"), test.get("name")) == validator.ALLOWED_SKIP)
    ElementTree.SubElement(target, "skipped", type="pytest.skip", message="native junctions are Windows-only")
    files["tests.xml"] = ElementTree.tostring(xml)
    result = validator.validate_python(files, "core")
    assert result["skipped"] == [list(validator.ALLOWED_SKIP)]
    assert len(result["passed"]) == 1884


@pytest.mark.parametrize("fault", ["missing", "duplicate", "skipped", "failure", "error"])
def test_extension_inventory_preserves_every_named_case(fault):
    files = FixtureAPI().gate_files("package-darwin-arm64")
    assert len(validator.validate_extension(files)["passed"]) == 48
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
