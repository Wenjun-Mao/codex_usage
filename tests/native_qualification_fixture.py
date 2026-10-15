"""Complete synthetic native evidence bound to an existing hosted proof."""
from hashlib import sha256

from qualification_fixture import policy
from release_tooling_support import load_tool

native = load_tool("release.native")


def native_evidence(hosted, manifest, package):
    labels = ["Tokens", "Project", "Estimated credits", "API cost", "Projects", "Estimated credits",
        "Tokens", "Other", "Time", "Hourly", "Previous", "Next", "Credit balance", "None", "Weekly allowance", "Daily",
        "day", "hour", "Projects", "project", "Daily"]
    inputs = [{"label": label, "requested": {"state": {"step": index}}, "rendered": {"state": {"step": index}}}
        for index, label in enumerate(labels)]
    inputs[-1]["keyboard"] = True
    return {"synthetic_only": True, "script_disabled": True, "strict_host_validation": True,
        "no_capture_command": True, "no_scripts_or_csp_relaxation": True, "rendered_input": inputs,
        "qualified_package": package, "binary_sha256": package["collector_sha256"],
        "qualification_input": {"hosted": {"receipt_id": hosted["receipt_id"], "receipt_digest": hosted["receipt_digest"],
            "manifest_sha256": policy.fingerprint(manifest)}, "package": package},
        "native_host": {"version": policy.HOST["version"], "commit": policy.HOST["commit"],
            "executable_sha256": "e"*64}, "native_vscode": policy.HOST["version"],
        "harness": {"metadata_patch": native.PATCH,
            "acceptance_sha256": sha256((policy.ROOT / native.HARNESS).read_bytes()).hexdigest()},
        "credential_isolation": "--use-inmemory-secretstorage; disposable HOME/CODEX_HOME/profile",
        "hover_and_tab": {"hover_within_250ms": True, "script_disabled": True, "numeric_format_readable": True,
            "native_title_inheritance_suppressed": True, "hover_seconds": [.025, .03],
            "tab_traversal": "CDP focus origin; real Tab reaches next usage bar"}}
