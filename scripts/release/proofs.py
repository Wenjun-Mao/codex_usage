"""Validate original producer execution, not copied latest-attempt job records."""
from hashlib import sha256
import json
import re

from verification.visual_cases import validate_inventory
from verification.hover_measurements import validate_summary
from verification.hover_process import validate_process
from run_visual_suite import SCRIPTS

from .archives import inspect_payload
from .policy import GATES, JOBS, REPOSITORY, SCHEMA, TARGETS, WORKFLOW, positive, require
from .producer import MARKER, artifact_name, validate_payload


def unique_job(jobs, name):
    matches = [job for job in jobs if job.get("name") == name]
    require(len(matches) == 1, f"Missing or duplicate required job: {name}")
    job = matches[0]
    require(job.get("status") == "completed" and job.get("conclusion") == "success"
        and job.get("started_at") and job.get("completed_at"), f"Unsuccessful required job: {name}")
    return job


def check_run(run, attempt, *, completed=True):
    require(run.get("repository", {}).get("full_name") == REPOSITORY
        and run.get("head_repository", {}).get("id") == run["repository"]["id"], "Untrusted repository/fork")
    require(run.get("event") == "workflow_dispatch" and run.get("path") == WORKFLOW
        and run.get("head_branch") == "main", "Untrusted qualification event/workflow/ref")
    require(positive(run.get("run_attempt")) == positive(attempt), "Superseded or unknown selected attempt")
    if completed:
        require(run.get("status") == "completed" and run.get("conclusion") == "success", "Qualification run is not successful")


def check_source(source, run, contract, version):
    require(source == {"repository": REPOSITORY, "repository_id": run["repository"]["id"],
        "sha": run["head_sha"], "version": version, "contract": contract, "workflow": WORKFLOW,
        "probe": source.get("probe")}, "Untrusted source/contract identity")
    require(type(source["probe"]) is bool, "Invalid probe declaration")


def check_marker(log, expected):
    markers = []
    log = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", log)
    for line in log.splitlines():
        match = re.fullmatch(r"(?:[0-9T:.Z+-]+\s+)?" + re.escape(MARKER) + r"(\{.*\})", line)
        if match:
            markers.append(json.loads(match[1]))
    require(markers == [expected], "Producer receipt lacks a unique original-job log marker")


class Proofs:
    def __init__(self, api, run_id, attempt, contract, version, blobs, *, completed=True):
        self.api, self.run_id, self.attempt = api, positive(run_id), positive(attempt)
        self.run = api.run(self.run_id)
        check_run(self.run, self.attempt, completed=completed)
        actual = api.contract_tree(self.run["head_sha"])
        require(blobs and all(actual.get(name) == value for name, value in blobs.items()),
            "Qualification source Git tree differs from trusted contract files")
        self.contract, self.version = contract, version
        self.selected_jobs = api.jobs(self.run_id, self.attempt)
        self.inventory = api.artifacts(self.run_id)
        self.cache = {}

    def receipt(self, gate, artifact_id, artifact_digest, *, payload=False):
        cache_key = (gate, positive(artifact_id), artifact_digest, payload)
        if cache_key in self.cache:
            return self.cache[cache_key]
        record, archive = self.api.artifact(artifact_id, artifact_digest, self.run)
        require(set(archive) == {"receipt.json"}, "Foreign receipt archive")
        receipt_data = archive["receipt.json"]
        receipt = json.loads(receipt_data)
        require(type(receipt.get("schema")) is int and receipt["schema"] == SCHEMA and receipt.get("gate") == gate and gate in JOBS,
            "Foreign receipt contract/gate")
        check_source(receipt["source"], self.run, self.contract, self.version)
        origin = receipt["origin"]
        attempt = positive(origin["attempt"])
        require(origin.get("run") == self.run_id and attempt <= self.attempt
            and origin.get("job_name") == JOBS[gate]
            and origin.get("job_key") == ("package" if gate.startswith("package-") else
                "visual" if gate.startswith("visual-") else gate), "Foreign producer run/attempt/job")
        require(record["name"] == artifact_name("receipt", gate, self.run_id, attempt), "Foreign receipt artifact name")
        original = unique_job(self.api.jobs(self.run_id, attempt), JOBS[gate])
        selected = unique_job(self.selected_jobs, JOBS[gate])
        require((original["started_at"], original["completed_at"]) ==
            (selected["started_at"], selected["completed_at"]), "Stale producer evidence after a newer execution")
        check_marker(self.api.logs(original["id"]), {"gate": gate, "run": self.run_id, "attempt": attempt,
            "receipt_id": positive(artifact_id), "receipt_digest": artifact_digest})
        uploaded = receipt["payload"]
        matches = [row for row in self.inventory if row["id"] == uploaded["id"]]
        require(len(matches) == 1 and matches[0]["name"] == artifact_name("payload", gate, self.run_id, attempt)
            and matches[0]["expired"] is False and matches[0]["digest"] == "sha256:" + uploaded["digest"],
            "Missing, expired or foreign producer payload")
        manifest = receipt["manifest"]
        require(type(manifest.get("schema")) is int and manifest["schema"] == SCHEMA and manifest.get("gate") == gate
            and manifest.get("source") == receipt["source"], "Foreign payload declaration")
        if gate.startswith("visual-"):
            children = [child for child, *_ in SCRIPTS[gate.removeprefix("visual-")]]
            require(set(manifest.get("visual", {})) == set(children), "Missing required visual suite")
            for child in children:
                validate_inventory(manifest["visual"][child], child)
                if child == "hover":
                    validate_summary(manifest["visual"][child].get("observation_summary"))
                    validate_process(manifest["visual"][child].get("process"))
        files = None
        if payload:
            _, transport = self.api.artifact(uploaded["id"], uploaded["digest"], self.run)
            require(set(transport) == {"payload.zip"}, "Foreign payload archive")
            metadata, files = inspect_payload(transport["payload.zip"], gate, receipt["source"])
            require(validate_payload(metadata, files, gate) == manifest, "Producer payload/declaration mismatch")
        result = {"receipt_id": positive(artifact_id), "receipt_digest": artifact_digest,
            "receipt_sha256": sha256(receipt_data).hexdigest(), "originating_attempt": attempt,
            "producer_job_id": original["id"], "selected_job_id": selected["id"],
            "receipt": receipt, "files": files}
        self.cache[cache_key] = result
        return result

    def resolve(self, gate, *, payload=False):
        unique_job(self.selected_jobs, JOBS[gate])
        candidates = []
        for row in self.inventory:
            match = re.fullmatch(r"receipt-" + re.escape(gate) + rf"-r{self.run_id}-a([1-9][0-9]*)", row["name"])
            if match and int(match[1]) <= self.attempt:
                candidates.append((int(match[1]), row))
        require(candidates, f"Missing producer receipt: {gate}")
        latest = max(attempt for attempt, _ in candidates)
        matches = [row for attempt, row in candidates if attempt == latest]
        require(len(matches) == 1, "Ambiguous producer receipt")
        row = matches[0]
        require(row.get("digest", "").startswith("sha256:"), "Missing immutable receipt digest")
        return self.receipt(gate, row["id"], row["digest"].removeprefix("sha256:"), payload=payload)

    @staticmethod
    def reference(proof):
        return {key: value for key, value in proof.items() if key not in ("receipt", "files", "selected_job_id")}

    def freeze(self):
        proofs = {gate: self.resolve(gate, payload=True) for gate in GATES}
        sources = [proof["receipt"]["source"] for proof in proofs.values()]
        require(all(source == sources[0] for source in sources), "Mixed qualification sources")
        return {"schema": SCHEMA, "source": sources[0], "run": self.run_id,
            "originating_attempt": self.attempt,
            "gates": {gate: self.reference(proof) for gate, proof in proofs.items()},
            "packages": {target: proofs[f"package-{target}"]["receipt"]["manifest"]["package"] for target in TARGETS}}

    def hosted(self):
        hosted = self.resolve("hosted", payload=True)
        files = hosted["files"]
        require("hosted.json" in files, "Missing frozen hosted manifest")
        manifest = json.loads(files["hosted.json"])
        require(manifest.get("schema") == SCHEMA and manifest.get("source") == hosted["receipt"]["source"]
            and manifest.get("run") == self.run_id and set(manifest.get("gates", {})) == set(GATES),
            "Foreign or incomplete hosted manifest")
        for gate, reference in manifest["gates"].items():
            proof = self.receipt(gate, reference["receipt_id"], reference["receipt_digest"],
                payload=gate == "visual-hover")
            require(self.reference(proof) == reference, "Frozen producer identity mismatch")
        return hosted, manifest
