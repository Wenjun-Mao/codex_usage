"""Independent preserved cases, complete collection and explicit platform skip policy."""
import json
from pathlib import Path
from xml.etree import ElementTree

BASELINE = Path(__file__).with_name("python-case-baseline.json")


def _xml_cases(raw):
    root = ElementTree.fromstring(raw)
    for suite in root.iter("testsuite"):
        cases = list(suite.iter("testcase"))
        expected = {"tests": len(cases), "failures": sum(case.find("failure") is not None for case in cases),
            "errors": sum(case.find("error") is not None for case in cases),
            "skipped": sum(case.find("skipped") is not None for case in cases)}
        if any(suite.get(key) is not None and suite.get(key) != str(value) for key, value in expected.items()):
            raise ValueError("Raw JUnit totals differ from individual results")
    return list(root.iter("testcase"))


def validate_python(files, scope):
    if "tests.xml" not in files or "inventory.json" not in files:
        raise ValueError("Missing passing-case/collection evidence")
    inventory = json.loads(files["inventory.json"])
    if (type(inventory.get("schema")) is not int or inventory["schema"] != 1 or inventory.get("scope") != scope
        or type(inventory.get("exitstatus")) is not int or inventory["exitstatus"] != 0
        or inventory.get("platform") not in ("Linux", "Darwin", "Windows")):
        raise ValueError("Unsuccessful or foreign test collection")
    tests = _xml_cases(files["tests.xml"])
    actual = [(test.get("classname"), test.get("name")) for test in tests]
    collected = [tuple(case) for case in inventory.get("collected", [])]
    if (not actual or any(len(case) != 2 or any(not isinstance(value, str) or not value for value in case) for case in collected)
        or len(actual) != len(set(actual)) or len(collected) != len(set(collected)) or set(actual) != set(collected)):
        raise ValueError("Missing, duplicated or uncollected Python test cases")
    required = {tuple(case) for case in json.loads(BASELINE.read_text())["required"]}
    if scope == "metadata":
        required = {case for case in required if case[0] in
            ("tests.test_github_actions_workflow", "tests.test_release_history")}
    if not required <= set(actual):
        raise ValueError(f"Required preserved test cases missing: {sorted(required-set(actual))[:5]}")
    skipped = []
    for test, case in zip(tests, actual, strict=True):
        if test.find("failure") is not None or test.find("error") is not None:
            raise ValueError("Required test did not pass")
        skip = test.find("skipped")
        if skip is not None:
            raise ValueError("Unapproved skipped test case")
    return {"collected": [list(case) for case in sorted(collected)],
        "passed": [list(case) for case in sorted(actual) if list(case) not in skipped],
        "skipped": skipped, "platform": inventory["platform"]}


def validate_extension(files):
    if "extension-tests.xml" not in files or "extension-inventory.json" not in files:
        raise ValueError("Missing extension test inventory/completion evidence")
    tests = _xml_cases(files["extension-tests.xml"])
    names = [test.get("name") for test in tests]
    required = set(json.loads(Path(__file__).with_name("extension-case-baseline.json").read_text())["required"])
    if len(names) != len(set(names)) or not required <= set(names) or any(
        test.find(tag) is not None for test in tests for tag in ("failure", "error", "skipped")):
        raise ValueError("Missing, duplicated, skipped or failed extension cases")
    inventory = json.loads(files["extension-inventory.json"])
    summaries = inventory.get("summaries", [])
    if (type(inventory.get("schema")) is not int or inventory["schema"] != 1 or inventory.get("complete") is not True
        or len(summaries) != 1 or summaries[0].get("success") is not True):
        raise ValueError("Incomplete extension runner")
    counts = summaries[0].get("counts", {})
    expected = {"tests": len(tests), "passed": len(tests), "failed": 0, "cancelled": 0, "skipped": 0, "todo": 0, "suites": 0}
    if any(type(counts.get(key)) is not int or counts[key] != value for key, value in expected.items()):
        raise ValueError("Extension completion counts differ")
    cases = inventory.get("cases", [])
    identities = [tuple(case["identity"]) for case in cases]
    collected = [tuple(case) for case in inventory.get("collected", [])]
    if (len(identities) != len(set(identities)) or len(collected) != len(set(collected))
        or set(identities) != set(collected) or sorted(case[1] for case in identities) != sorted(names)
        or any(case.get("outcome") != "passed" or case.get("skipped") is not False or case.get("todo") is not False for case in cases)):
        raise ValueError("Extension case events differ from complete passing inventory")
    return {"passed": sorted(names), "identities": [list(case) for case in sorted(identities)]}
