"""Local progress hints and bounded command execution, never publication proof."""
from contextlib import contextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile
from time import monotonic

from filelock import FileLock

from .policy import ROOT, canonical, fingerprint, require


class Pending(ValueError):
    """An external result is unknown; reconciliation must not repeat its effect."""


def now():
    return datetime.now(UTC).isoformat()


def atomic_bytes(path, value):
    path = Path(path)
    require(not path.is_symlink(), "Symlinked progress/document destination")
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_json(path, value):
    atomic_bytes(path, canonical(value))


def command(args, *, root=ROOT, timeout=1800, capture=False, strip=True):
    require(not os.environ.get("VSCE_PAT"), "Local release tools must not receive publisher credentials")
    result = subprocess.run([str(a) for a in args], cwd=root, check=True, timeout=timeout,
        text=True, stdout=subprocess.PIPE if capture else None)
    return (result.stdout.strip() if strip else result.stdout) if capture else None


class Progress:
    def __init__(self, directory, candidate):
        self.directory = Path(directory).resolve()
        require(self.directory.is_relative_to((ROOT / "output").resolve()), "Progress must stay under ignored output/")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "process.json"
        self.candidate = candidate
        parent = ROOT / "output/releases/process-intents"
        parent.mkdir(parents=True, exist_ok=True)
        require(parent.resolve().is_relative_to((ROOT / "output").resolve()), "Canonical intents escape ignored output/")
        # Resolve only the parent: resolving the final file would conceal a symlink.
        self.shared = parent.resolve() / (fingerprint(candidate) + ".json")
        self.lock_path = parent.parent.resolve() / "release-process.lock"

    @contextmanager
    def locked(self):
        require(not self.lock_path.is_symlink(), "Symlinked coordinator lock")
        with FileLock(self.lock_path, timeout=0):
            require(not self.path.is_symlink(), "Symlinked process state")
            self.data = json.loads(self.path.read_text()) if self.path.exists() else {
                "schema": 1, "candidate": self.candidate, "operations": {}, "timings": []}
            require(self.data.get("schema") == 1 and self.data.get("candidate") == self.candidate,
                "Progress candidate/schema differs; do not reset or borrow state")
            require(isinstance(self.data.get("operations"), dict) and isinstance(self.data.get("timings"), list),
                "Malformed progress")
            require(not self.shared.is_symlink(), "Symlinked canonical intents")
            self.intents = json.loads(self.shared.read_text()) if self.shared.exists() else {
                "schema": 1, "candidate": self.candidate, "operations": {}}
            require(self.intents.get("schema") == 1 and self.intents.get("candidate") == self.candidate
                and isinstance(self.intents.get("operations"), dict), "Canonical intents differ")
            for name in ("tag", "dry-run", "promotion"):
                local, shared = self.data["operations"].get(name), self.intents["operations"].get(name)
                require(local is None or (isinstance(local, dict) and isinstance(shared, dict)
                    and all(shared.get(k) == v for k, v in local.items())),
                    "Local publication hint lacks matching canonical intent")
                if shared is not None:
                    self.data["operations"][name] = shared
            self.save()
            yield self

    def save(self):
        for name in ("tag", "dry-run", "promotion"):
            operation = self.data["operations"].get(name)
            if operation is not None:
                self.intents["operations"][name] = operation
        atomic_json(self.shared, self.intents)
        atomic_json(self.path, self.data)

    @contextmanager
    def phase(self, name):
        row = {"phase": name, "started_at": now(), "status": "running"}
        self.data["timings"].append(row)
        self.save()
        started = monotonic()
        try:
            yield
        except BaseException:
            row["status"] = "interrupted-or-failed"
            raise
        else:
            row["status"] = "completed"
        finally:
            row.update(completed_at=now(), seconds=monotonic() - started)
            self.save()

    def mark(self, status):
        self.data["status"] = status
        self.save()
        print(json.dumps({"status": status, "progress": str(self.path)}, sort_keys=True), flush=True)
