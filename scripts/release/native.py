"""Qualified-package input preparation and exact native replay evidence."""
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import shutil

from .archives import extract_extension, file_identity
from .policy import HOST, canonical, fingerprint, require

PATCH = {"activationEvents": []}
HARNESS = "scripts/vscode_breakdown_acceptance.js"


def prepare_extension(repo, extension, vsix=None):
    extension = Path(extension)
    qualified = None
    source = Path(repo) / "extensions/vscode"
    if vsix is not None:
        data = Path(vsix).read_bytes()
        from zipfile import ZipFile
        with ZipFile(vsix) as archive:
            version = json.loads(archive.read("extension/package.json"))["version"]
        qualified = extract_extension(data, extension, version)
    else:
        extension.mkdir()
        shutil.copytree(source / "out", extension / "out")
        binary = extension / "bin/darwin-arm64/codex-usage-agent"
        binary.parent.mkdir(parents=True)
        shutil.copy2(Path(repo) / "build/packaged-agent/aarch64-apple-darwin/codex-usage-agent-aarch64-apple-darwin", binary)
        shutil.copy2(source / "package.json", extension / "package.json")
    original = json.loads((extension / "package.json").read_text())
    manifest = {**original, **PATCH}
    (extension / "package.json").write_text(json.dumps(manifest))
    shutil.copy2(Path(repo) / HARNESS, extension / "acceptance.js")
    require({key: value for key, value in manifest.items() if key != "activationEvents"}
        == {key: value for key, value in original.items() if key != "activationEvents"}, "Undeclared native metadata patch")
    if qualified:
        for name, identity in qualified["assets"].items():
            if name != "extension/package.json":
                require(file_identity((extension / name.removeprefix("extension/")).read_bytes()) == identity,
                    "Native harness changed a shipped asset")
    return qualified


def host_identity(code):
    code = Path(code).resolve()
    app = code.parents[1] / "Resources/app"
    product = json.loads((app / "product.json").read_text())
    return {"version": product["version"], "commit": product["commit"],
        "executable_sha256": sha256(code.read_bytes()).hexdigest()}


def bind_evidence(evidence, repo, code, package, qualification):
    evidence["qualified_package"] = package
    evidence["qualification_input"] = qualification
    evidence["native_host"] = host_identity(code)
    evidence["harness"] = {"metadata_patch": PATCH,
        "acceptance_sha256": sha256((Path(repo) / HARNESS).read_bytes()).hexdigest()}
    if qualification is not None:
        require(package == qualification["package"], "Native package differs from hosted qualification")
    return evidence


def validate_native(evidence, hosted, manifest, package):
    require(evidence.get("synthetic_only") is True and evidence.get("script_disabled") is True
        and evidence.get("strict_host_validation") is True and evidence.get("no_capture_command") is True
        and evidence.get("no_scripts_or_csp_relaxation") is True, "Incomplete native safety evidence")
    require(evidence.get("qualified_package") == package and evidence.get("binary_sha256") == package["collector_sha256"],
        "Native VSIX/collector/assets mismatch")
    expected = {"hosted": {"receipt_id": hosted["receipt_id"], "receipt_digest": hosted["receipt_digest"],
            "manifest_sha256": fingerprint(manifest)}, "package": package}
    require(evidence.get("qualification_input") == expected, "Native proof binds another hosted manifest")
    require(evidence.get("native_host", {}).get("version") == HOST["version"]
        and evidence["native_host"].get("commit") == HOST["commit"]
        and evidence.get("native_vscode") == HOST["version"], "Foreign native host")
    require(evidence.get("harness", {}).get("metadata_patch") == PATCH, "Undeclared native harness patch")
    inputs = evidence.get("rendered_input", [])
    labels = ["Tokens", "Project", "Estimated credits", "API cost", "Projects", "Estimated credits",
        "Tokens", "Other", "Time", "Hourly", "Previous", "Next", "Credit balance", "None", "Weekly allowance", "Daily"]
    require(len(inputs) == 21 and [item.get("label") for item in inputs[:16]] == labels
        and inputs[18].get("label") == "Projects" and inputs[-1].get("keyboard") is True,
        "Missing or reordered native rendered input inventory")
    require(all(item["requested"]["state"] == item["rendered"]["state"] for item in inputs),
        "Native command/rendered state mismatch")
    hover = evidence.get("hover_and_tab", {})
    require(hover.get("hover_within_250ms") is True and hover.get("script_disabled") is True
        and hover.get("numeric_format_readable") is True and hover.get("native_title_inheritance_suppressed") is True
        and len(hover.get("hover_seconds", [])) == 2 and all(
            type(value) in (int, float) and 0 <= value < .25 and isfinite(value) for value in hover["hover_seconds"])
        and hover.get("tab_traversal") == "CDP focus origin; real Tab reaches next usage bar",
        "Missing native hover/focus evidence")
    require("--use-inmemory-secretstorage" in evidence.get("credential_isolation", ""), "Native credentials not isolated")


def write_native_input(directory, hosted, manifest, package, vsix):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "qualified.vsix").write_bytes(vsix)
    qualification = {"hosted": {"receipt_id": hosted["receipt_id"], "receipt_digest": hosted["receipt_digest"],
        "manifest_sha256": fingerprint(manifest)}, "package": package}
    (directory / "qualification-input.json").write_bytes(canonical(qualification))
    return qualification
