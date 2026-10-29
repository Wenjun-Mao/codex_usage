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
    validate_theme_journey(evidence.get("theme_journey", {}))
    hover = evidence.get("hover_and_tab", {})
    require(hover.get("hover_within_250ms") is True and hover.get("script_disabled") is True
        and hover.get("numeric_format_readable") is True and hover.get("native_title_inheritance_suppressed") is True
        and len(hover.get("hover_seconds", [])) == 2 and all(
            type(value) in (int, float) and 0 <= value < .25 and isfinite(value) for value in hover["hover_seconds"])
        and hover.get("tab_traversal") == "CDP focus origin; real Tab reaches next usage bar",
        "Missing native hover/focus evidence")
    require("--use-inmemory-secretstorage" in evidence.get("credential_isolation", ""), "Native credentials not isolated")


def validate_theme_journey(theme):
    """Validate native theme states, colors and origin/response scopes."""
    updates = theme.get("updates", [])
    require(theme.get("script_disabled") is True and len(updates) == 5
        and [u.get("theme") for u in updates] == ["night", "day", "auto", "auto", "night"]
        and [u.get("serial") for u in updates] == list(range(1, 6))
        and updates[2].get("editor_theme") == "Default Dark Modern"
        and updates[3].get("editor_theme") == "Default Light Modern",
        "Missing complete native theme/configuration journey")
    require(all(u.get("complete_content") is True and u.get("configuration_persisted") is True
        and u.get("breakdown") == theme.get("initial_state")
        and u.get("speed") == theme.get("initial_speed")
        and u.get("allowance") == theme.get("initial_allowance") and bool(u.get("screenshot"))
        and type(u.get("seconds")) in (int, float) and 0 <= u["seconds"] < 30 and isfinite(u["seconds"])
        for u in updates), "Incomplete native themed content/state/persistence evidence")
    require(updates[0].get("background") == updates[-1].get("background") == "rgb(16, 19, 22)"
        and updates[0].get("color") == updates[-1].get("color") == "rgb(237, 242, 245)"
        and updates[1].get("background") == "rgb(245, 247, 249)"
        and updates[1].get("color") == "rgb(23, 32, 39)"
        and updates[2].get("background") == "rgb(31, 31, 31)"
        and updates[2].get("color") == "rgb(204, 204, 204)"
        and updates[3].get("background") == "rgb(245, 247, 249)"
        and updates[3].get("color") == "rgb(23, 32, 39)"
        and all(u.get("color") and u.get("color") != u.get("background") for u in updates),
        "Native theme colors or editor Auto behavior differ")
    require(theme.get("initial_speed", {}).get("granularity") == "hourly"
        and type(theme["initial_speed"].get("window_start")) is str
        and theme.get("initial_allowance", {}).get("state", {}).get("kind") == "periods"
        and theme["initial_allowance"].get("inspection_visible") is True
        and theme["initial_allowance"].get("has_observations") is True
        and bool(theme["initial_allowance"].get("inspection_sha256"))
        and len(theme["initial_allowance"].get("scope", "")) == 64
        and theme["initial_allowance"]["scope"] == theme["initial_allowance"].get("accepted_scope"),
        "Missing seeded nondefault native speed/history state")
    for owner in ("breakdown", "allowance"):
        action = theme.get(owner, {})
        require(action.get("requested", {}).get("state") is not None
            and action["requested"]["state"] == action.get("rendered", {}).get("state"),
            "Missing native issued theme action: " + owner)
    require(theme["breakdown"].get("before", {}).get("state") != theme["breakdown"]["requested"]["state"]
        and theme["allowance"]["rendered"].get("inspection_visible") is True
        and theme["allowance"]["rendered"].get("has_observations") is True
        and bool(theme["allowance"]["rendered"].get("inspection_sha256"))
        and theme["allowance"]["requested"].get("scope") == theme["initial_allowance"]["scope"]
        and theme["allowance"]["rendered"].get("scope") == theme["allowance"]["rendered"].get("accepted_scope")
        and len(theme["allowance"]["rendered"].get("scope", "")) == 64
        and theme["allowance"]["rendered"]["scope"] != theme["initial_allowance"]["scope"]
        and theme["allowance"]["rendered"]["state"] != theme["initial_allowance"]["state"]
        and theme["allowance"]["rendered"]["inspection_sha256"] != theme["initial_allowance"]["inspection_sha256"],
        "Native theme actions did not visibly change state")
    speed = theme.get("speed", {})
    require(speed.get("requested", {}).get("granularity") == speed.get("rendered", {}).get("granularity") == "daily"
        and speed["requested"].get("windowStart") == speed["rendered"].get("window_start")
        and bool(theme.get("action_screenshot")), "Missing native issued theme speed action")


def write_native_input(directory, hosted, manifest, package, vsix):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "qualified.vsix").write_bytes(vsix)
    qualification = {"hosted": {"receipt_id": hosted["receipt_id"], "receipt_digest": hosted["receipt_digest"],
        "manifest_sha256": fingerprint(manifest)}, "package": package}
    (directory / "qualification-input.json").write_bytes(canonical(qualification))
    return qualification
