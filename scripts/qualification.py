"""Produce, freeze and inspect exact qualified platform artifacts; never rebuild."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess

from release.archives import make_payload
from release.github import GitHub
from release.native import validate_native, write_native_input
from release.policy import JOBS, PROMOTION_BLOCKER, PROMOTION_ENABLED, PROMOTION_WORKFLOW, REPOSITORY, ROOT, SCHEMA, TARGETS, canonical, contract_blobs, contract_identity, fingerprint, package_version, positive, require
from release.producer import make_receipt, marker, source_context
from release.proofs import Proofs


def proof_reader(args, *, completed):
    return Proofs(GitHub(), args.run, args.attempt, contract_identity(ROOT), package_version(ROOT),
        contract_blobs(ROOT), completed=completed)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(data))


def fetch_package(proofs, hosted, manifest, directory):
    target = "darwin-arm64"
    reference = manifest["gates"][f"package-{target}"]
    proof = proofs.receipt(f"package-{target}", reference["receipt_id"], reference["receipt_digest"], payload=True)
    package = proof["receipt"]["manifest"]["package"]
    require(package == manifest["packages"][target], "Hosted package identity mismatch")
    name = proof["receipt"]["manifest"]["package_file"]
    return write_native_input(directory, hosted, manifest, package, proof["files"][name])


def inspect_qualified(proofs, directory):
    hosted, manifest = proofs.hosted()
    require(manifest["source"].get("probe") is False, "Fault-injection runs are not release candidates")
    require(set(manifest.get("packages", {})) == set(TARGETS), "Missing qualified target")
    native = proofs.resolve("native", payload=True)
    require("evidence.json" in native["files"] and "host.json" in native["files"], "Missing trusted native evidence/host record")
    evidence = json.loads(native["files"]["evidence.json"])
    validate_native(evidence, hosted, manifest, manifest["packages"]["darwin-arm64"])
    host = json.loads(native["files"]["host.json"])
    from release.policy import HOST
    require(all(host.get(key) == value for key, value in HOST.items())
        and host.get("executable_sha256") == evidence["native_host"]["executable_sha256"], "Native host provenance mismatch")
    expected_harness = sha256((ROOT / "scripts/vscode_breakdown_acceptance.js").read_bytes()).hexdigest()
    require(evidence["harness"].get("acceptance_sha256") == expected_harness, "Native harness identity mismatch")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for target in TARGETS:
        reference = manifest["gates"][f"package-{target}"]
        proof = proofs.receipt(f"package-{target}", reference["receipt_id"], reference["receipt_digest"], payload=True)
        require(proof["receipt"]["manifest"]["package"] == manifest["packages"][target], "Qualified target differs from frozen manifest")
        data = proof["files"][proof["receipt"]["manifest"]["package_file"]]
        (directory / f"codex-usage-companion-{target}.vsix").write_bytes(data)
    result = {"schema": SCHEMA, "status": "qualified-not-published", "source": manifest["source"],
        "qualification_run": proofs.run_id, "qualification_attempt": proofs.attempt,
        "hosted": proofs.reference(hosted), "native": proofs.reference(native), "manifest": manifest,
        "manifest_sha256": fingerprint(manifest)}
    write_json(directory / "qualified.json", result)
    return result


def check_release_tag(api, source, ref):
    tag = "v" + source["version"]
    require(ref == "refs/tags/" + tag, "Publication requires dispatching a matching version tag")
    record = api.json(f"{api.prefix}/git/ref/tags/{tag}")["object"]
    for _ in range(4):
        if record["type"] == "commit":
            break
        require(record["type"] == "tag", "Unexpected release ref type")
        record = api.json(f"{api.prefix}/git/tags/{record['sha']}")["object"]
    require(record["type"] == "commit" and record["sha"] == source["sha"], "Release tag does not peel to qualified source")
    ancestry = api.json(f"{api.prefix}/compare/{source['sha']}...main")
    require(ancestry["merge_base_commit"]["sha"] == source["sha"]
        and ancestry["status"] in ("ahead", "identical"), "Qualified source is not contained in main")
    return tag


def check_promotion_dispatch(api, source, ref, run_id, attempt, env=os.environ):
    run_id, attempt = positive(run_id), positive(attempt)
    run = api.run(run_id)
    require(run.get("repository", {}).get("full_name") == REPOSITORY
        and run.get("head_repository", {}).get("id") == run["repository"]["id"]
        and run.get("path") == PROMOTION_WORKFLOW and run.get("event") == "workflow_dispatch",
        "Untrusted promotion dispatch")
    require(run.get("head_sha") == source["sha"] and ref == "refs/tags/v" + source["version"]
        and run.get("head_branch") == "v" + source["version"] and positive(run.get("run_attempt")) == attempt,
        "Immutable promotion dispatch differs from qualified source/tag/attempt")
    if env.get("GITHUB_ACTIONS") == "true":
        require(positive(env["GITHUB_RUN_ID"]) == run_id and positive(env["GITHUB_RUN_ATTEMPT"]) == attempt
            and env.get("GITHUB_SHA") == source["sha"] and env.get("GITHUB_REF") == ref,
            "Actual publisher dispatch context differs")
    return {"run": run_id, "attempt": attempt, "sha": source["sha"], "ref": ref}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    package = commands.add_parser("payload")
    package.add_argument("--gate", choices=JOBS, required=True)
    package.add_argument("--directory", type=Path, required=True)
    package.add_argument("--output", type=Path, required=True)
    package.add_argument("--package", type=Path)
    receipt = commands.add_parser("receipt")
    receipt.add_argument("--gate", choices=JOBS, required=True)
    receipt.add_argument("--payload", type=Path, required=True)
    receipt.add_argument("--artifact-id", required=True)
    receipt.add_argument("--artifact-digest", required=True)
    receipt.add_argument("--output", type=Path, required=True)
    stamp = commands.add_parser("marker")
    stamp.add_argument("--gate", choices=JOBS, required=True)
    stamp.add_argument("--artifact-id", required=True)
    stamp.add_argument("--artifact-digest", required=True)
    for name in ("freeze", "fetch-native", "inspect", "validate-publication"):
        command = commands.add_parser(name)
        command.add_argument("--run", type=positive, required=True)
        command.add_argument("--attempt", type=positive, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "validate-publication":
            command.add_argument("--ref", required=True)
            command.add_argument("--promotion-run", type=positive, required=True)
            command.add_argument("--promotion-attempt", type=positive, required=True)
    check = commands.add_parser("check-files")
    check.add_argument("--directory", type=Path, required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command in ("validate-publication", "check-files"):
        require(PROMOTION_ENABLED, PROMOTION_BLOCKER)
    if args.command == "payload":
        source = source_context(ROOT)
        target = args.gate.removeprefix("package-") if args.gate.startswith("package-") else None
        if args.package:
            require(target is not None, "Package input requires a platform gate")
            args.directory.mkdir(parents=True, exist_ok=True)
            shutil.copy2(args.package, args.directory / args.package.name)
        make_payload(args.directory, args.output, args.gate, source, target=target, version=source["version"])
    elif args.command == "receipt":
        write_json(args.output, make_receipt(ROOT, args.gate, args.payload.read_bytes(), args.artifact_id, args.artifact_digest))
    elif args.command == "marker":
        print(marker(args.gate, os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"], args.artifact_id, args.artifact_digest))
    elif args.command == "check-files":
        result = json.loads((args.directory / "qualified.json").read_text())
        require(result.get("schema") == SCHEMA and result.get("status") == "validated-for-publication", "Not publication-authorized proof")
        require(result.get("manifest_sha256") == fingerprint(result["manifest"])
            and result["source"] == result["manifest"]["source"]
            and result["source"]["contract"] == contract_identity(ROOT), "Publisher source/manifest identity changed")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
        require(head == result["promotion"]["publisher_sha"], "Publisher revision changed after validation")
        for target in TARGETS:
            from release.archives import package_identity
            data = (args.directory / f"codex-usage-companion-{target}.vsix").read_bytes()
            require(package_identity(data, target, result["source"]["version"]) == result["manifest"]["packages"][target],
                "Publisher upload file changed after validation")
    else:
        proofs = proof_reader(args, completed=args.command in ("inspect", "validate-publication"))
        if args.command == "freeze":
            write_json(args.output / "hosted.json", proofs.freeze())
        elif args.command == "fetch-native":
            hosted, manifest = proofs.hosted()
            fetch_package(proofs, hosted, manifest, args.output)
        else:
            result = inspect_qualified(proofs, args.output)
            if args.command == "validate-publication":
                result["promotion"] = check_promotion_dispatch(proofs.api, result["source"], args.ref,
                    args.promotion_run, args.promotion_attempt)
                if os.environ.get("GITHUB_ACTIONS") == "true":
                    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                        text=True, capture_output=True, check=True).stdout.strip()
                else:
                    from release.publication_history import publisher_revision
                    revision = publisher_revision(proofs.api, args.promotion_run, args.promotion_attempt, contract_blobs(ROOT))
                result["promotion"]["publisher_sha"] = revision
                result["tag"] = check_release_tag(proofs.api, result["source"], args.ref)
                result["status"] = "validated-for-publication"
                write_json(args.output / "qualified.json", result)
            print(json.dumps({"status": result["status"], "source": result["source"], "run": args.run, "attempt": args.attempt}))


if __name__ == "__main__":
    main()
