"""Synthetic coordinator boundary transport; never sends Git or account calls."""
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import parse_qs

from release_tooling_support import load_tool

policy = load_tool("release.policy")
CANDIDATE = {"repository": policy.REPOSITORY, "sha": "a" * 40, "version": "2.12.6", "contract": "b" * 64}


def qualified():
    source = {**CANDIDATE, "probe": False}
    packages = {target: {"sha256": sha256(target.encode()).hexdigest(), "bytes": len(target)} for target in policy.TARGETS}
    manifest = {"source": source, "packages": packages}
    return {"schema": 1, "status": "qualified-not-published", "source": source,
        "manifest": manifest, "manifest_sha256": policy.fingerprint(manifest),
        "qualification_run": 100, "qualification_attempt": 1, "timing_disposition": "hosted-webkit-observed"}


def job(name, conclusion="success"):
    return {"name": name, "conclusion": conclusion, "status": "completed", "steps": [],
        "created_at": "2026-10-17T20:00:00Z", "started_at": "2026-10-17T20:00:01Z",
        "completed_at": "2026-10-17T20:00:20Z"}


class Transport:
    prefix = "repos/" + policy.REPOSITORY

    def __init__(self):
        self.runs, self.calls = {}, []
        self.qualified = qualified()
        self.lose = None
        self.artifact_mismatch = False
        self.bad_inspection = False

    def raw(self, endpoint):
        if endpoint.endswith("/git/ref/heads/main"):
            return json.dumps({"object": {"sha": CANDIDATE["sha"]}})
        if "/actions/runs?" in endpoint:
            query = parse_qs(endpoint.split("?", 1)[1])
            rows = [r for r in self.runs.values() if r["head_sha"] == query["head_sha"][0]
                and r["head_branch"] == query["branch"][0]]
            return json.dumps({"total_count": len(rows), "workflow_runs": rows})
        return json.dumps(self.runs[int(endpoint.rsplit("/", 1)[1])])

    def pages(self, endpoint, field):
        return json.loads(self.raw(endpoint))[field]

    def jobs(self, run, attempt):
        record = self.runs[run]
        if record["path"] == policy.WORKFLOW:
            return [job("Core and accounting")]
        return [job("Validate qualification"), job("Publish qualified packages",
            "skipped" if " dry-run=true " in record["display_title"] else "success")]

    def artifacts(self, run):
        return [{"id": 123, "name": f"qualification-inspection-r{run}-a1", "digest": "sha256:" + "c" * 64}]

    def artifact(self, identifier, digest, run):
        return {}, {"qualified.json": b"wrong" if self.artifact_mismatch else policy.canonical(self.qualified)}

    def command(self, args, **kwargs):
        args = [str(a) for a in args]
        self.calls.append(args)
        if args[:3] == ["gh", "workflow", "run"]:
            workflow = ".github/workflows/" + args[3]
            fields = dict(args[i+1].split("=", 1) for i, value in enumerate(args) if value in ("--raw-field", "--field"))
            ref = args[args.index("--ref") + 1]
            identifier = 100 + len(self.runs)
            if workflow == policy.WORKFLOW:
                title = f"Qualify Codex Usage VSIX ref={ref} probe=false request={fields['request_id']}"
            else:
                title = (f"Promote qualified run={fields['qualification_run']} attempt={fields['qualification_attempt']} "
                    f"dry-run={fields['dry_run']} request={fields['request_id']}")
            self.runs[identifier] = {"id": identifier, "repository": {"id": 123, "full_name": policy.REPOSITORY},
                "head_repository": {"id": 123}, "head_sha": CANDIDATE["sha"], "head_branch": ref,
                "path": workflow, "event": "workflow_dispatch", "run_attempt": 1,
                "status": "completed", "conclusion": "success", "display_title": title,
                "created_at": "2026-10-17T20:00:00Z", "updated_at": "2026-10-17T20:00:20Z"}
            if self.lose == workflow:
                raise TimeoutError("reply was lost after acceptance")
        elif "scripts/qualification.py" in args:
            directory = Path(args[args.index("--output") + 1])
            directory.mkdir(parents=True, exist_ok=True)
            data = {**self.qualified}
            if self.bad_inspection:
                data["source"] = {**data["source"], "sha": "f" * 40}
            (directory / "qualified.json").write_bytes(policy.canonical(data))
        elif "scripts/verify_marketplace_release.cjs" in args:
            directory = Path(args[args.index("--output") + 1])
            publication = int(args[args.index("--promotion-run") + 1])
            write_public(directory, publication=publication)
        else:
            raise AssertionError(f"Unexpected command: {args}")


def write_public(directory, *, publication=102):
    directory.mkdir(parents=True, exist_ok=True)
    q = {**qualified(), "status": "validated-for-publication", "tag": "v2.12.6",
        "promotion": {"run": publication, "attempt": 1, "sha": CANDIDATE["sha"],
            "ref": "refs/tags/v2.12.6", "publisher_sha": CANDIDATE["sha"]}}
    targets = []
    for target in policy.TARGETS:
        (directory / f"official-{target}.vsix").write_bytes(target.encode())
        targets.append({"target": target, **q["manifest"]["packages"][target],
            "qualifiedArtifactEqual": True, "catalogHashEqual": True})
    public = {"schema": 1, "version": "2.12.6", "tag": "v2.12.6", "commit": CANDIDATE["sha"],
        "verifiedAt": "2026-10-18T01:33:18Z", "qualificationRun": 100, "qualificationAttempt": 1,
        "promotionRun": publication, "promotionAttempt": 1, "targets": targets}
    for name, data in {"qualified.json": q, "verification.json": public,
        "publisher-proof.json": {"promotion": q["promotion"], "prior_intents": dict.fromkeys(policy.TARGETS, True)}}.items():
        (directory / name).write_bytes(policy.canonical(data))
    return public, q
