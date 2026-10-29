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
    theme_state = {"scope": "a"*64, "state": {"metric": "tokens"}}
    initial_speed = {"granularity": "hourly", "window_start": "2026-10-01"}
    initial_allowance = {"scope": "a"*64, "state": {"kind": "periods", "index": 0}, "inspection_visible": True,
        "has_observations": True, "inspection_sha256": "f"*64}
    changed_allowance = dict(initial_allowance, scope="b"*64, state={"kind": "periods", "index": 1}, inspection_sha256="e"*64)
    theme = {"initial_speed": initial_speed, "initial_allowance": initial_allowance, "script_disabled": True, "initial_state": theme_state, "updates": [],
        "breakdown": {"before": {"state": {"metric": "cost"}}, "requested": theme_state, "rendered": theme_state},
        "allowance": {"requested": {"scope": "b"*64, "state": changed_allowance["state"]}, "rendered": changed_allowance},
        "speed": {"requested": {"granularity": "daily"}, "rendered": {"granularity": "daily"}},
        "action_screenshot": "theme-actions.png"}
    for serial, (name, editor, color) in enumerate([
        ("night", None, "rgb(16, 19, 22)"), ("day", None, "rgb(245, 247, 249)"),
        ("auto", "Default Dark Modern", "rgb(31, 31, 31)"),
        ("auto", "Default Light Modern", "rgb(245, 247, 249)"), ("night", None, "rgb(16, 19, 22)")], 1):
        theme["updates"].append({"serial": serial, "theme": name, "editor_theme": editor,
            "background": color, "color": "rgb(237, 242, 245)" if name == "night" else "rgb(204, 204, 204)" if editor == "Default Dark Modern" else "rgb(23, 32, 39)", "complete_content": True,
            "configuration_persisted": True, "breakdown": theme_state, "speed": initial_speed, "allowance": initial_allowance, "screenshot": "theme.png", "seconds": .1})
    return {"theme_journey": theme, "synthetic_only": True, "script_disabled": True, "strict_host_validation": True,
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
