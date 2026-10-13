"""Bind successful job outputs to immutable uploads and explicit origin attempts."""
import json
import os
import subprocess

from verification.visual_cases import validate_inventory
from verification.test_inventory import validate_extension, validate_python
from run_visual_suite import SCRIPTS

from .archives import inspect_payload
from .policy import JOBS, REPOSITORY, SCHEMA, WORKFLOW, canonical, contract_files, contract_identity, digest, package_version, positive, require

MARKER = "CODEX_GATE_RECEIPT "


def source_context(root, env=os.environ):
    require(env.get("GITHUB_REPOSITORY") == REPOSITORY and env.get("GITHUB_REF") == "refs/heads/main"
        and env.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "Qualification requires trusted main dispatch")
    sha = env["GITHUB_SHA"]
    require(sha == env.get("QUALIFICATION_WORKFLOW_SHA"), "Source and workflow SHA differ")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    require(head == sha, "Actual checkout HEAD differs from declared source")
    files = contract_files(root)
    subprocess.run(["git", "ls-files", "--error-unmatch", "--", *files], cwd=root,
        check=True, capture_output=True)
    subprocess.run(["git", "diff", "--exit-code", "HEAD"], cwd=root,
        check=True, capture_output=True)
    return {"repository": REPOSITORY, "repository_id": positive(env["GITHUB_REPOSITORY_ID"]),
        "sha": sha, "version": package_version(root), "contract": contract_identity(root),
        "workflow": WORKFLOW, "probe": env.get("QUALIFICATION_PROBE", "false") == "true"}


def artifact_name(kind, gate, run, attempt):
    require(kind in ("payload", "receipt") and gate in JOBS, "Unknown producer artifact")
    return f"{kind}-{gate}-r{positive(run)}-a{positive(attempt)}"


def validate_payload(metadata, files, gate):
    if gate.startswith("visual-"):
        suite = gate.removeprefix("visual-")
        require(suite in SCRIPTS, "Unknown visual gate")
        visual = {}
        for child, *_ in SCRIPTS[suite]:
            path = f"{child}/verification.json"
            require(path in files, "Missing visual case evidence")
            evidence = json.loads(files[path])
            validate_inventory(evidence, child)
            visual[child] = {key: evidence[key] for key in
                ("schema", "suite", "status", "synthetic_only", "assertions", "completed")}
            if child in ("breakdown", "speed"):
                require(f"{child}/evidence.json" in files, "Missing work-counter evidence")
                performance = json.loads(files[f"{child}/evidence.json"])["performance"]
                key = "warm_history_materializations_fits_reprices" if child == "breakdown" else "warm_monetary_materializations"
                require(type(performance.get(key)) is int and performance[key] == 0, "Warm historical work was not bounded")
        metadata["visual"] = visual
    elif gate in ("core", "metadata"):
        metadata["tests"] = validate_python(files, gate)
    elif gate.startswith("package-"):
        metadata["extension_tests"] = validate_extension(files)
    return metadata


def make_receipt(root, gate, payload_data, payload_id, payload_digest, env=os.environ):
    require(gate in JOBS, "Unknown gate")
    source = source_context(root, env)
    metadata, files = inspect_payload(payload_data, gate, source)
    metadata = validate_payload(metadata, files, gate)
    run, attempt = positive(env["GITHUB_RUN_ID"]), positive(env["GITHUB_RUN_ATTEMPT"])
    return {"schema": SCHEMA, "source": source, "gate": gate,
        "origin": {"run": run, "attempt": attempt, "job_key": env["GITHUB_JOB"], "job_name": JOBS[gate]},
        "payload": {"id": positive(payload_id), "digest": digest(payload_digest),
            "name": artifact_name("payload", gate, run, attempt)}, "manifest": metadata}


def marker(gate, run, attempt, receipt_id, receipt_digest):
    return MARKER + canonical({"gate": gate, "run": positive(run), "attempt": positive(attempt),
        "receipt_id": positive(receipt_id), "receipt_digest": digest(receipt_digest)}).decode().strip()
