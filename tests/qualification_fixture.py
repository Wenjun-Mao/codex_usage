"""In-memory original/reused GitHub executions and cryptographically bound uploads."""
from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZipFile
from xml.etree import ElementTree

from release_tooling_support import load_tool
from hover_measurement_fixture import PROCESS, hosted_measurements, measurements

policy = load_tool("release.policy")
archives = load_tool("release.archives")
producer = load_tool("release.producer")
GitHub = load_tool("release.github").GitHub
Proofs = load_tool("release.proofs").Proofs
cases = load_tool("verification.visual_cases")


def zip_bytes(files):
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()


def package_bytes(target="darwin-arm64", version="2.12.2"):
    manifest = {"publisher": "wenjun-mao", "name": "codex-usage-dashboard",
        "version": version, "activationEvents": ["onStartupFinished"]}
    xml = (f'<PackageManifest xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">'
        f'<Metadata><Identity Id="codex-usage-dashboard" Version="{version}" Publisher="wenjun-mao" '
        f'TargetPlatform="{target}"/></Metadata></PackageManifest>').encode()
    return zip_bytes({"extension/package.json": policy.canonical(manifest),
        "extension.vsixmanifest": xml, "extension/out/extension.js": b"shipped JavaScript",
        archives.AGENTS[target]: b"collector-" + target.encode()})


def visual_evidence(suite, *, hover=None):
    result = {"schema": 2 if suite == "hover" else 1, "suite": suite,
        "status": "functional-complete" if suite == "hover" else "passed", "synthetic_only": True,
        "assertions": list(cases.ASSERTIONS[suite]), "completed": cases.expected_cases(suite)}
    if suite == "hover":
        result.update(measurements() if hover is None else hover)
    return result


class FixtureAPI(GitHub):
    def __init__(self):
        super().__init__()
        self.responses, self.bodies, self.uploads, self.job_rows = {}, {}, [], {}
        self.source = {"repository": policy.REPOSITORY, "repository_id": 123,
            "sha": "a" * 40, "version": "2.12.2", "contract": "b" * 64,
            "workflow": policy.WORKFLOW, "probe": False}
        self.hover, self.journal = hosted_measurements(self.source)
        self.run_data = {"id": 77, "run_attempt": 1, "head_sha": self.source["sha"],
            "repository": {"id": 123, "full_name": policy.REPOSITORY}, "head_repository": {"id": 123},
            "event": "workflow_dispatch", "path": policy.WORKFLOW, "head_branch": "main",
            "status": "completed", "conclusion": "success"}
        self.blobs = {policy.WORKFLOW: "f" * 40, policy.PROMOTION_WORKFLOW: "c" * 40,
            "extensions/vscode/scripts/cliEntrypoints.js": "e" * 40}
        for index, (gate, name) in enumerate(policy.JOBS.items()):
            self.job_rows[gate] = {"id": 1000 + index, "name": name, "run_attempt": 1,
                "status": "completed", "conclusion": "success",
                "started_at": f"2026-10-13T00:{index:02}:00Z", "completed_at": f"2026-10-13T00:{index:02}:20Z"}
        self.jobs_by_attempt = {1: list(self.job_rows.values())}
        for gate in policy.GATES:
            self.add_gate(gate, self.gate_files(gate))

    def reader(self):
        return Proofs(self, 77, self.run_data["run_attempt"], self.source["contract"], self.source["version"], self.blobs,
            journal=self.journal)

    def contract_tree(self, source_sha):
        assert source_sha == self.source["sha"]
        return self.blobs.copy()

    def raw(self, endpoint):
        if endpoint in self.bodies:
            return self.bodies[endpoint]
        if endpoint in self.responses:
            return policy.canonical(self.responses[endpoint])
        if endpoint == f"{self.prefix}/actions/runs/77":
            return policy.canonical(self.run_data)
        if "/attempts/" in endpoint:
            attempt = int(endpoint.split("/attempts/")[1].split("/")[0])
            return policy.canonical({"jobs": self.jobs_by_attempt[attempt]})
        if endpoint.startswith(f"{self.prefix}/actions/runs/77/artifacts?"):
            return policy.canonical({"artifacts": self.uploads})
        raise AssertionError(f"Unexpected API request: {endpoint}")

    def gate_files(self, gate):
        if gate.startswith("package-"):
            names = json.loads((policy.ROOT / "scripts/verification/extension-case-baseline.json").read_text())["required"]
            xml = ElementTree.Element("testsuite")
            for name in names:
                ElementTree.SubElement(xml, "testcase", name=name)
            identities = [["test/fixture.test.js", name] for name in names]
            inventory = {"schema": 1, "complete": True, "collected": identities,
                "cases": [{"identity": case, "outcome": "passed", "skipped": False, "todo": False} for case in identities],
                "summaries": [{"success": True, "counts": {"tests": len(names), "passed": len(names),
                    "failed": 0, "cancelled": 0, "skipped": 0, "todo": 0, "suites": 0}}]}
            return {"package.vsix": package_bytes(gate.removeprefix("package-")),
                "extension-tests.xml": ElementTree.tostring(xml), "extension-inventory.json": policy.canonical(inventory)}
        if gate in ("metadata", "core"):
            validator = load_tool("verification.test_inventory")
            required = json.loads(validator.BASELINE.read_text())["required"]
            if gate == "metadata":
                required = [case for case in required if case[0] in ("tests.test_github_actions_workflow", "tests.test_release_history")]
            xml = ElementTree.Element("testsuite")
            for classname, name in required:
                ElementTree.SubElement(xml, "testcase", classname=classname, name=name)
            return {"tests.xml": ElementTree.tostring(xml), "inventory.json": policy.canonical({"schema": 1,
                "scope": gate, "exitstatus": 0, "platform": "Linux", "collected": required})}
        suites = load_tool("run_visual_suite").SCRIPTS[gate.removeprefix("visual-")]
        files = {}
        for suite, *_ in suites:
            files[f"{suite}/verification.json"] = policy.canonical(visual_evidence(suite, hover=self.hover))
            if suite == "hover":
                files["hover/process.json"] = policy.canonical(PROCESS)
            key = "warm_history_materializations_fits_reprices" if suite == "breakdown" else "warm_monetary_materializations"
            files[f"{suite}/evidence.json"] = policy.canonical({"performance": {key: 0}})
        return files

    def upload(self, name, files):
        identifier = 10000 + len(self.uploads)
        data = zip_bytes(files)
        record = {"id": identifier, "name": name, "digest": "sha256:" + sha256(data).hexdigest(),
            "size_in_bytes": len(data), "expired": False,
            "workflow_run": {"id": 77, "head_sha": self.source["sha"], "repository_id": 123, "head_repository_id": 123}}
        self.uploads.append(record)
        self.responses[f"{self.prefix}/actions/artifacts/{identifier}"] = record
        self.bodies[f"{self.prefix}/actions/artifacts/{identifier}/zip"] = data
        return record

    def add_gate(self, gate, files, attempt=1):
        metadata = {"schema": 1, "gate": gate, "source": self.source,
            "files": {name: archives.file_identity(data) for name, data in sorted(files.items())}}
        if gate.startswith("package-"):
            metadata.update(package_file="package.vsix",
                package=archives.package_identity(files["package.vsix"], gate.removeprefix("package-"), self.source["version"]))
        payload = zip_bytes({**files, "payload.json": policy.canonical(metadata)})
        uploaded = self.upload(producer.artifact_name("payload", gate, 77, attempt), {"payload.zip": payload})
        origin = {"run": 77, "attempt": attempt, "job_name": policy.JOBS[gate],
            "job_key": "package" if gate.startswith("package-") else "visual" if gate.startswith("visual-") else gate}
        metadata = producer.validate_payload(metadata, files, gate, origin=origin, journal=self.journal)
        receipt = {"schema": 1, "gate": gate, "source": self.source,
            "origin": origin,
            "payload": {"id": uploaded["id"], "digest": uploaded["digest"].removeprefix("sha256:"), "name": uploaded["name"]},
            "manifest": metadata}
        record = self.upload(producer.artifact_name("receipt", gate, 77, attempt), {"receipt.json": policy.canonical(receipt)})
        self.bodies[f"{self.prefix}/actions/jobs/{self.job_rows[gate]['id']}/logs"] = (
            "2026-10-13T00:00:00.000Z " + producer.marker(gate, 77, attempt, record["id"], record["digest"].removeprefix("sha256:")) + "\n").encode()
        self._cache.clear()
        return record

    def rewrite_receipt(self, gate, change):
        row = next(row for row in self.uploads if row["name"].startswith(f"receipt-{gate}-"))
        files = archives.zip_files(self.bodies[f"{self.prefix}/actions/artifacts/{row['id']}/zip"])
        receipt = json.loads(files["receipt.json"])
        change(receipt)
        data = zip_bytes({"receipt.json": policy.canonical(receipt)})
        row.update(digest="sha256:" + sha256(data).hexdigest(), size_in_bytes=len(data))
        self.bodies[f"{self.prefix}/actions/artifacts/{row['id']}/zip"] = data
        # Keep the log stamp matching to test checks beyond transport integrity.
        origin = receipt["origin"]
        self.bodies[f"{self.prefix}/actions/jobs/{self.job_rows[gate]['id']}/logs"] = (
            producer.marker(gate, 77, origin["attempt"], row["id"], row["digest"].removeprefix("sha256:")) + "\n").encode()
        self._cache.clear()
