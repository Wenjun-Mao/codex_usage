"""Thin orchestration over independent qualification, publisher and public proof."""
import json
import sys

from .github import GitHub
from .policy import WORKFLOW, PROMOTION_WORKFLOW, canonical, positive, require
from .process_candidate import assert_remote_main, unchanged
from .process_preflight import preflight
from .process_receipts import checked_public, pinned_verification, write_receipt
from .process_runs import dispatch, finish
from .process_state import Pending, atomic_bytes, atomic_json, command
from .process_tag import ensure_tag
from .process_timings import comparison, workflow_timing


class Coordinator:
    def __init__(self, progress, *, api=None, run_command=command, seconds=1800):
        self.progress, self.api = progress, api or GitHub()
        self.command, self.seconds = run_command, seconds

    def workflow(self, name, *, workflow, ref, fields=None, allow=False):
        dispatch(self.progress, self.api, name, workflow=workflow, ref=ref, fields=fields,
            allow=allow, run_command=self.command)
        run = finish(self.progress, self.api, name, seconds=self.seconds)
        jobs = self.api.jobs(run["id"], run["run_attempt"])
        timing = workflow_timing(run, jobs)
        self.progress.data.setdefault("workflows", {})[name] = timing
        self.progress.save()
        return run, jobs

    def inspect(self, run, attempt):
        directory = self.progress.directory / "inspection"
        self.command([sys.executable, "scripts/qualification.py", "inspect", "--run", run,
            "--attempt", attempt, "--output", directory])
        qualified = json.loads((directory / "qualified.json").read_text())
        require(all(qualified["source"].get(k) == v for k, v in self.progress.candidate.items())
            and qualified["source"].get("probe") is False and qualified["qualification_run"] == run
            and qualified["qualification_attempt"] == attempt, "Independent inspection source/run differs")
        return qualified

    def prepare(self, base, *, reuse=None, allow=True):
        if "promotion" in self.progress.data["operations"]:
            raise Pending("Publication was already requested; resume its observation instead")
        unchanged(self.progress.candidate)
        if not self.progress.data["operations"].get("qualification"):
            if not allow:
                raise Pending("No qualification dispatched; explicit prepare is required")
            with self.progress.phase("local-preflight"):
                result = preflight(base, self.progress.directory, reuse=reuse, run_command=self.command)
            self.progress.data["preflight"] = result
            self.progress.save()
        unchanged(self.progress.candidate)
        assert_remote_main(self.api, self.progress.candidate)
        run, _ = self.workflow("qualification", workflow=WORKFLOW, ref="main", allow=allow)
        with self.progress.phase("qualification-inspection"):
            self.inspect(run["id"], run["run_attempt"])
        self.progress.mark("qualified-not-published")
        self.summary()
        return run

    def dry_run(self, run, attempt, *, allow=False, announce=True):
        if allow:
            unchanged(self.progress.candidate)
            assert_remote_main(self.api, self.progress.candidate)
        with self.progress.phase("independent-inspection"):
            qualified = self.inspect(run, attempt)
        dry, jobs = self.workflow("dry-run", workflow=PROMOTION_WORKFLOW, ref="main",
            fields={"qualification_run": str(run), "qualification_attempt": str(attempt), "dry_run": "true"}, allow=allow)
        require(len(jobs) == 2 and {j["name"]: j["conclusion"] for j in jobs} == {
            "Validate qualification": "success", "Publish qualified packages": "skipped"},
            "Dry-run must validate proof and skip its publisher")
        records = self.api.artifacts(dry["id"])
        name = f"qualification-inspection-r{dry['id']}-a{dry['run_attempt']}"
        matches = [row for row in records if row["name"] == name]
        require(len(matches) == 1, "Missing or duplicate dry-run inspection")
        row = matches[0]
        _, files = self.api.artifact(row["id"], row["digest"].removeprefix("sha256:"), dry)
        require(set(files) == {"qualified.json"} and files["qualified.json"] == canonical(qualified),
            "Independent/hosted inspections differ")
        self.progress.data["selected"] = {"run": run, "attempt": attempt}
        self.progress.save()
        if announce and "promotion" not in self.progress.data["operations"]:
            self.progress.mark("dry-run-complete-not-published")
        self.summary()
        return dry

    def promote(self, run, attempt):
        unchanged(self.progress.candidate)
        self.dry_run(run, attempt, allow=True)
        unchanged(self.progress.candidate)
        with self.progress.phase("tag-reconciliation"):
            tag = ensure_tag(self.progress, self.api, allow=True, run_command=self.command)
        self.progress.mark("publication-request-pending")
        published, _ = self.workflow("promotion", workflow=PROMOTION_WORKFLOW, ref=tag,
            fields={"qualification_run": str(run), "qualification_attempt": str(attempt), "dry_run": "false"}, allow=True)
        return self.verify(run, attempt, published["id"], published["run_attempt"])

    def verify(self, run, attempt, promotion, promotion_attempt):
        self.progress.mark("uploaded-public-verification-pending")
        dry = self.dry_run(run, attempt, allow=False, announce=False)
        directory = self.progress.directory / "public"
        with self.progress.phase("public-verification"):
            self.command(["node", "scripts/verify_marketplace_release.cjs", "--qualification-run", run,
                "--qualification-attempt", attempt, "--promotion-run", promotion,
                "--promotion-attempt", promotion_attempt, "--output", directory], timeout=3600)
        public, qualified = checked_public(directory, self.progress.candidate)
        public = pinned_verification(self.progress, public, qualified)
        self.progress.mark("publicly-verified-receipt-pending")
        with self.progress.phase("receipt-generation"):
            path = write_receipt(self.progress, public, qualified, dry)
        self.progress.mark("publicly-verified")
        self.summary()
        return path

    def resume(self, base):
        operations = self.progress.data["operations"]
        if "promotion" in operations:
            op = operations["promotion"]
            run, _ = self.workflow("promotion", workflow=PROMOTION_WORKFLOW,
                ref="v" + self.progress.candidate["version"], fields=op["fields"])
            return self.verify(positive(op["fields"]["qualification_run"]), positive(op["fields"]["qualification_attempt"]),
                run["id"], run["run_attempt"])
        if "dry-run" in operations:
            op = operations["dry-run"]
            self.dry_run(positive(op["fields"]["qualification_run"]), positive(op["fields"]["qualification_attempt"]), allow=False)
            raise Pending("Dry-run reconciled; explicit promote is required to cross the publication boundary")
        return self.prepare(base, allow=False)

    def summary(self):
        data = {"status": self.progress.data.get("status"), "candidate": self.progress.candidate,
            "phases": self.progress.data["timings"], "workflows": self.progress.data.get("workflows", {})}
        atomic_json(self.progress.directory / "timings.json", data)
        atomic_bytes(self.progress.directory / "timings.md", comparison(data["workflows"]).encode())
