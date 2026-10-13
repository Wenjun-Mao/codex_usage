"""Read-only GitHub API with explicit archive digests and paginated inventories."""
from hashlib import sha256
import json
import os
import subprocess

from .archives import zip_files
from .policy import MAX_ARCHIVE, REPOSITORY, digest, positive, require


class GitHub:
    def __init__(self):
        require(os.environ.get("GH_HOST", "github.com") == "github.com", "Untrusted GitHub host")
        self.repo = REPOSITORY
        self.prefix = f"repos/{self.repo}"
        self._cache = {}

    def raw(self, endpoint):
        result = subprocess.run(["gh", "api", "--hostname", "github.com", "--allow-escape-sequences", endpoint],
            capture_output=True, check=True, timeout=90)
        require(len(result.stdout) <= MAX_ARCHIVE, "API response exceeds bounds")
        return result.stdout

    def json(self, endpoint):
        if endpoint not in self._cache:
            self._cache[endpoint] = json.loads(self.raw(endpoint))
        return self._cache[endpoint]

    def pages(self, endpoint, field):
        rows, page, total = [], 1, None
        while True:
            separator = "&" if "?" in endpoint else "?"
            result = self.json(f"{endpoint}{separator}per_page=100&page={page}")
            if "total_count" in result:
                require(type(result["total_count"]) is int and result["total_count"] >= 0, "Invalid API inventory total")
                if total is None:
                    total = result["total_count"]
                require(total == result["total_count"], "API inventory changed during pagination")
            batch = result[field]
            rows.extend(batch)
            if len(batch) < 100:
                require(total is None or len(rows) == total, "Incomplete API inventory")
                require(len([row["id"] for row in rows]) == len({row["id"] for row in rows}), "Duplicated API inventory")
                return rows
            page += 1
            require(page <= 100, "Excessive API inventory")

    def run(self, run_id):
        return self.json(f"{self.prefix}/actions/runs/{positive(run_id)}")

    def jobs(self, run_id, attempt):
        return self.pages(f"{self.prefix}/actions/runs/{positive(run_id)}/attempts/{positive(attempt)}/jobs", "jobs")

    def artifacts(self, run_id):
        return self.pages(f"{self.prefix}/actions/runs/{positive(run_id)}/artifacts", "artifacts")

    def artifact(self, artifact_id, expected_digest, run):
        artifact_id = positive(artifact_id)
        record = self.json(f"{self.prefix}/actions/artifacts/{artifact_id}")
        require(record.get("id") == artifact_id and record.get("expired") is False,
            "Missing, replaced or expired artifact")
        require(record.get("workflow_run", {}).get("id") == run["id"]
            and record["workflow_run"].get("head_sha") == run["head_sha"]
            and record["workflow_run"].get("repository_id") == run["repository"]["id"]
            and record["workflow_run"].get("head_repository_id") == run["repository"]["id"],
            "Foreign artifact run/source/repository")
        expected_digest = digest(expected_digest)
        require(record.get("digest") == "sha256:" + expected_digest, "REST artifact digest mismatch")
        data = self.raw(f"{self.prefix}/actions/artifacts/{artifact_id}/zip")
        require(sha256(data).hexdigest() == expected_digest and len(data) == record["size_in_bytes"],
            "Downloaded artifact digest/size mismatch")
        return record, zip_files(data)

    def logs(self, job_id):
        return self.raw(f"{self.prefix}/actions/jobs/{positive(job_id)}/logs").decode("utf-8")

    def contract_tree(self, source_sha):
        commit = self.json(f"{self.prefix}/git/commits/{source_sha}")
        tree = self.json(f"{self.prefix}/git/trees/{commit['tree']['sha']}?recursive=1")
        require(tree.get("truncated") is False, "Source Git tree is incomplete")
        return {row["path"]: row["sha"] for row in tree["tree"] if row["type"] == "blob"}
