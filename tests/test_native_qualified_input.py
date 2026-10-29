"""Native replay cannot drift from the qualified package or hosted manifest."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from qualification_fixture import FixtureAPI, package_bytes, policy
from native_qualification_fixture import native_evidence
from release_tooling_support import load_tool

native = load_tool("release.native")


def bound_native():
    api = FixtureAPI()
    manifest = api.reader().freeze()
    api.add_gate("hosted", {"hosted.json": policy.canonical(manifest)})
    hosted, manifest = api.reader().hosted()
    package = manifest["packages"]["darwin-arm64"]
    return hosted, manifest, package, native_evidence(hosted, manifest, package)


@pytest.mark.parametrize("fault", ["package", "collector", "hosted", "manifest", "host", "patch", "script",
    "csp", "credentials", "inputs", "reorder", "state", "latency", "tab"])
def test_native_proof_is_complete_and_matches_exact_qualified_inputs(fault):
    hosted, manifest, package, evidence = bound_native()
    native.validate_native(evidence, hosted, manifest, package)
    evidence = deepcopy(evidence)
    if fault == "package":
        evidence["qualified_package"]["sha256"] = "c"*64
    elif fault == "collector":
        evidence["binary_sha256"] = "c"*64
    elif fault == "hosted":
        evidence["qualification_input"]["hosted"]["receipt_id"] += 1
    elif fault == "manifest":
        evidence["qualification_input"]["hosted"]["manifest_sha256"] = "c"*64
    elif fault == "host":
        evidence["native_host"]["commit"] = "c"*40
    elif fault == "patch":
        evidence["harness"]["metadata_patch"] = {"enableScripts": True}
    elif fault == "script":
        evidence["script_disabled"] = False
    elif fault == "csp":
        evidence["no_scripts_or_csp_relaxation"] = False
    elif fault == "credentials":
        evidence["credential_isolation"] = "default profile"
    elif fault == "inputs":
        evidence["rendered_input"].pop()
    elif fault == "reorder":
        evidence["rendered_input"][0]["label"] = "Capture Usage"
    elif fault == "state":
        evidence["rendered_input"][0]["rendered"]["state"] = {"step": 1}
    elif fault == "latency":
        evidence["hover_and_tab"]["hover_seconds"][0] = .25
    else:
        evidence["hover_and_tab"]["tab_traversal"] = "unproven"
    with pytest.raises(ValueError):
        native.validate_native(evidence, hosted, manifest, package)


def test_native_preparation_extracts_exact_assets_and_only_declared_metadata_patch(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    harness = repo / native.HARNESS
    harness.write_text("approved harness")
    vsix = tmp_path / "qualified.vsix"
    data = package_bytes()
    vsix.write_bytes(data)
    extension = tmp_path / "extension"
    package = native.prepare_extension(repo, extension, vsix)
    assert package["sha256"] == sha256(data).hexdigest()
    assert (extension / "out/extension.js").read_bytes() == b"shipped JavaScript"
    assert (extension / "acceptance.js").read_text() == "approved harness"
    manifest = json.loads((extension / "package.json").read_text())
    assert manifest["activationEvents"] == [] and manifest["version"] == "2.12.2"
    assert (extension / "bin/darwin-arm64/codex-usage-agent").stat().st_mode & 0o111
    with pytest.raises(ValueError, match="fresh"):
        native.prepare_extension(repo, extension, vsix)


@pytest.mark.parametrize("value", [False, True, None, ".01", -.1, .25, float("nan"), float("inf"), 10**1000])
def test_native_latency_samples_are_finite_numbers_not_boolean_passes(value):
    hosted, manifest, package, evidence = bound_native()
    evidence["hover_and_tab"]["hover_seconds"][0] = value
    with pytest.raises(ValueError, match="hover/focus"):
        native.validate_native(evidence, hosted, manifest, package)


def test_contract_identity_normalizes_checkout_endings_not_semantic_changes(tmp_path, monkeypatch):
    root = tmp_path
    file = root / "source.py"
    monkeypatch.setattr(policy, "contract_files", lambda root: ["source.py"])
    file.write_bytes(b"approved\nsource\n")
    before = policy.contract_identity(root)
    file.write_bytes(b"approved\r\nsource\r\n")
    assert policy.contract_identity(root) == before
    file.write_bytes(b"changed\r\nsource\r\n")
    assert policy.contract_identity(root) != before


@pytest.mark.parametrize("fault", ["missing", "update", "order", "color", "auto", "content", "state", "persistence", "timing", "action", "speed", "speed-reset", "history-reset", "hidden-inspection", "noop", "allowance-scope", "inspection-stale"])
def test_native_theme_journey_is_required_and_fail_closed(fault):
    hosted, manifest, package, evidence = bound_native()
    native.validate_native(evidence, hosted, manifest, package)
    theme = evidence["theme_journey"]
    if fault == "missing":
        del evidence["theme_journey"]
    elif fault == "update":
        theme["updates"].pop()
    elif fault == "order":
        theme["updates"][0]["theme"] = "day"
    elif fault == "color":
        theme["updates"][1]["background"] = "rgb(16, 19, 22)"
    elif fault == "auto":
        theme["updates"][2]["background"] = theme["updates"][3]["background"]
    elif fault == "content":
        theme["updates"][0]["complete_content"] = False
    elif fault == "state":
        theme["updates"][0]["breakdown"] = {"state": {"lost": True}}
    elif fault == "persistence":
        theme["updates"][0]["configuration_persisted"] = False
    elif fault == "timing":
        theme["updates"][0]["seconds"] = float("nan")
    elif fault == "action":
        theme["allowance"]["rendered"] = {"state": {"lost": True}}
    elif fault == "speed":
        theme["speed"]["rendered"]["granularity"] = "hourly"
    elif fault == "speed-reset":
        theme["updates"][0]["speed"] = {"granularity": "daily"}
    elif fault == "history-reset":
        theme["updates"][0]["allowance"] = {"state": {"kind": ""}}
    elif fault == "hidden-inspection":
        theme["allowance"]["rendered"]["inspection_visible"] = False
    elif fault == "allowance-scope":
        theme["allowance"]["rendered"]["scope"] = "c"*64
    elif fault == "inspection-stale":
        theme["allowance"]["rendered"]["inspection_sha256"] = theme["initial_allowance"]["inspection_sha256"]
    else:
        theme["breakdown"]["before"] = theme["breakdown"]["requested"]
    with pytest.raises(ValueError, match="[Nn]ative|theme"):
        native.validate_native(evidence, hosted, manifest, package)
