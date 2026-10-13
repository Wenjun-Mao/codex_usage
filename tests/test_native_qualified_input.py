"""Native replay cannot drift from the qualified package or hosted manifest."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from qualification_fixture import FixtureAPI, package_bytes, policy
from release_tooling_support import load_tool

native = load_tool("release.native")


def bound_native():
    api = FixtureAPI()
    manifest = api.reader().freeze()
    api.add_gate("hosted", {"hosted.json": policy.canonical(manifest)})
    hosted, manifest = api.reader().hosted()
    package = manifest["packages"]["darwin-arm64"]
    labels = ["Tokens", "Project", "Estimated credits", "API cost", "Projects", "Estimated credits",
        "Tokens", "Other", "Time", "Hourly", "Previous", "Next", "Credit balance", "None", "Weekly allowance", "Daily",
        "day", "hour", "Projects", "project", "Daily"]
    inputs = [{"label": label, "requested": {"state": {"step": index}}, "rendered": {"state": {"step": index}}}
        for index, label in enumerate(labels)]
    inputs[-1]["keyboard"] = True
    evidence = {"synthetic_only": True, "script_disabled": True, "strict_host_validation": True,
        "no_capture_command": True, "no_scripts_or_csp_relaxation": True, "rendered_input": inputs,
        "qualified_package": package, "binary_sha256": package["collector_sha256"],
        "qualification_input": {"hosted": {"receipt_id": hosted["receipt_id"], "receipt_digest": hosted["receipt_digest"],
            "manifest_sha256": policy.fingerprint(manifest)}, "package": package},
        "native_host": {"version": policy.HOST["version"], "commit": policy.HOST["commit"]},
        "native_vscode": policy.HOST["version"],
        "harness": {"metadata_patch": native.PATCH},
        "credential_isolation": "--use-inmemory-secretstorage; disposable HOME/CODEX_HOME/profile",
        "hover_and_tab": {"hover_within_250ms": True, "script_disabled": True, "numeric_format_readable": True,
            "native_title_inheritance_suppressed": True, "hover_seconds": [.025, .03],
            "tab_traversal": "CDP focus origin; real Tab reaches next usage bar"}}
    return hosted, manifest, package, evidence


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
