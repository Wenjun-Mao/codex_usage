"""Enabled publication entrypoints with real validators and in-memory transports."""
from copy import deepcopy
import json
from types import SimpleNamespace

from qualification_fixture import FixtureAPI, policy
from native_qualification_fixture import native_evidence
from release_tooling_support import load_tool

history = load_tool("release.publication_history")


class PublicationFixture(FixtureAPI):
    publisher_sha = "d"*40

    def __init__(self, *, purpose="release", probe=False):
        super().__init__(version="2.12.3", binding_purpose=purpose, probe=probe)
        manifest = self.reader().freeze()
        self.add_gate("hosted", {"hosted.json": policy.canonical(manifest)})
        hosted, manifest = self.reader().hosted()
        evidence = native_evidence(hosted, manifest, manifest["packages"]["darwin-arm64"])
        self.add_gate("native", {"evidence.json": policy.canonical(evidence),
            "host.json": policy.canonical({**policy.HOST, "executable_sha256": "e"*64})})
        self.publisher_tree = self.blobs.copy()
        self.publication = {**self.run_data, "id": 88, "workflow_id": self.journal.config["workflow_id"],
            "path": policy.PROMOTION_WORKFLOW, "head_branch": "v2.12.3", "run_attempt": 1}
        self.validation_job = {"id": 5000, "name": "Validate qualification", "status": "completed",
            "conclusion": "success", "started_at": "2026-10-15T00:00:00Z",
            "completed_at": "2026-10-15T00:00:10Z"}

    def raw(self, endpoint):
        if endpoint == f"{self.prefix}/actions/runs/88":
            return policy.canonical(self.publication)
        if endpoint == f"{self.prefix}/git/ref/tags/v2.12.3":
            return policy.canonical({"object": {"type": "commit", "sha": self.source["sha"]}})
        if endpoint == f"{self.prefix}/compare/{self.source['sha']}...main":
            return policy.canonical({"merge_base_commit": {"sha": self.source["sha"]}, "status": "identical"})
        return super().raw(endpoint)

    def contract_tree(self, source_sha):
        return self.publisher_tree.copy() if source_sha == self.publisher_sha else super().contract_tree(source_sha)

    def jobs(self, run_id, attempt):
        return [deepcopy(self.validation_job)] if run_id == 88 else super().jobs(run_id, attempt)

    def logs(self, job_id):
        return history.CHECKOUT + self.publisher_sha + "\n" if job_id == 5000 else super().logs(job_id)

    def install(self, monkeypatch, qualification):
        monkeypatch.setattr(qualification, "PROMOTION_ENABLED", True)
        monkeypatch.setattr(qualification, "proof_reader", lambda *args, **kwargs: self.reader())
        monkeypatch.setattr(qualification, "contract_identity", lambda *args: self.source["contract"])
        monkeypatch.setattr(qualification, "contract_blobs", lambda *args: self.blobs.copy())

        def git_head(command, **kwargs):
            assert command == ["git", "rev-parse", "HEAD"]
            return SimpleNamespace(stdout=self.publisher_sha)

        monkeypatch.setattr(qualification.subprocess, "run", git_head)
        for name, value in {"GITHUB_ACTIONS": "true", "GITHUB_JOB": "publish", "GITHUB_RUN_ID": "88",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": self.source["sha"],
            "GITHUB_REF": "refs/tags/v2.12.3"}.items():
            monkeypatch.setenv(name, value)
        monkeypatch.delenv("VSCE_PAT", raising=False)

    def validate(self, qualification, directory):
        qualification.main(["validate-publication", "--run", "77", "--attempt", "1",
            "--ref", "refs/tags/v2.12.3", "--promotion-run", "88", "--promotion-attempt", "1",
            "--output", str(directory)])
        return json.loads((directory / "qualified.json").read_text())

    def install_writer(self, monkeypatch, tool):
        monkeypatch.setattr(tool, "PROMOTION_ENABLED", True)
        monkeypatch.setattr(tool, "configuration", lambda domain: self.journal.config)
        monkeypatch.setattr(tool, "contract_blobs", lambda: self.blobs.copy())
        def transport(domain):
            assert domain == "production"
            self._cache.clear()
            return self

        monkeypatch.setattr(tool, "JournalAPI", transport)
        monkeypatch.setattr(tool, "Journal", lambda api: self.journal)
