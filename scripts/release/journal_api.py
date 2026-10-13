"""Narrow Git Data mutations; no force, delete, arbitrary refs or secret output."""
import json
import subprocess

from .github import GitHub
from .journal_model import configuration
from .policy import canonical, require


class GitWriteError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(f"Git Data write rejected ({status}): {message}")


class JournalAPI(GitHub):
    def __init__(self, domain, config=None, *, bootstrap=False):
        super().__init__()
        self.config = configuration(domain, config, pinned=not bootstrap)
        self.bootstrap = bootstrap

    def write(self, method, endpoint, payload):
        ref = self.config["ref"].removeprefix("refs/")
        allowed = (method == "POST" and endpoint in ("git/blobs", "git/trees", "git/commits")) or (
            method == "PATCH" and endpoint == "git/refs/" + ref and payload.get("force") is False)
        if self.bootstrap and method == "POST" and endpoint == "git/refs":
            allowed = payload.get("ref") == self.config["ref"]
        require(allowed, "Forbidden Git Data mutation")
        result = subprocess.run(["gh", "api", "--hostname", "github.com", "--method", method,
            "--input", "-", f"{self.prefix}/{endpoint}"], input=canonical(payload), capture_output=True, timeout=90)
        response = json.loads(result.stdout)
        if result.returncode:
            raise GitWriteError(response.get("status", "unknown"), response.get("message", "write failed"))
        return response
