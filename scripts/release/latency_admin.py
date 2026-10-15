"""Explicit prepare/append lifecycle for an owner-approved frozen candidate."""
from copy import deepcopy
from hashlib import sha256
import json
import subprocess

from .git_journal import Journal, blob_sha
from .journal_api import JournalAPI
from .journal_model import git_sha
from .journal_state import retained_state
from .latency_bindings import EXCEPTION_ID, MAX_BINDINGS, SCOPE, binding_event
from .policy import (PROMOTION_ENABLED, REPOSITORY, ROOT, WORKFLOW, canonical,
    contract_files, fingerprint, require)


def frozen_source(root, journal):
    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    require(git("symbolic-ref", "--short", "HEAD") == "main", "D4 binding requires retained main")
    sha = git_sha(git("rev-parse", "HEAD"))
    git("ls-files", "--error-unmatch", "--", *contract_files(root))
    git("diff", "--exit-code", "HEAD")
    repo = journal.api.json(journal.api.prefix)
    require(repo["id"] == journal.config["repository_id"] and repo["full_name"] == REPOSITORY,
        "D4 preparation repository differs")
    remote = json.loads(journal.api.raw(f"{journal.api.prefix}/git/ref/heads/main"))
    require(remote["ref"] == "refs/heads/main" and remote["object"]["type"] == "commit"
        and remote["object"]["sha"] == sha,
        "D4 source is not the frozen pushed main candidate")
    contents = {name: (root / name).read_bytes().replace(b"\r\n", b"\n") for name in contract_files(root)}
    tree = journal.api.contract_tree(sha)
    require(contents and all(tree.get(name) == blob_sha(data) for name, data in contents.items()),
        "D4 frozen execution closure differs from committed Git objects")
    return {"repository": REPOSITORY, "repository_id": journal.config["repository_id"],
        "sha": sha, "version": json.loads(contents["extensions/vscode/package.json"])["version"],
        "contract": fingerprint({name: sha256(data).hexdigest() for name, data in contents.items()}), "workflow": WORKFLOW}


def require_purpose(purpose):
    require(purpose != "release" or PROMOTION_ENABLED,
        "Release binding requires the separately qualified enabled policy source")


def prepare(release_version, purpose, approval, *, root=ROOT, journal=None):
    journal = journal or Journal(JournalAPI("production"))
    require_purpose(purpose)
    source = frozen_source(root, journal)
    snapshot = journal.read()
    previous = retained_state(snapshot["records"], journal.config).binding
    value = {"slot": {"id": EXCEPTION_ID, "release_version": release_version,
        "max_bindings": MAX_BINDINGS, "scope": deepcopy(SCOPE)},
        "revision": previous["event"]["binding"]["revision"]+1 if previous else 1,
        "supersedes": previous["commit"] if previous else None,
        "purpose": purpose, "source": source, "approval": approval}
    event = binding_event(value, journal.config)
    retained_state(snapshot["records"], journal.config).admit(event)
    return {"schema": 1, "kind": "prepared-d4-binding", "expected_head": snapshot["head"], "binding": value}


def append(prepared, *, root=ROOT, journal=None):
    journal = journal or Journal(JournalAPI("production"))
    require(isinstance(prepared, dict) and set(prepared) == {"schema", "kind", "expected_head", "binding"}
        and type(prepared["schema"]) is int and prepared["schema"] == 1
        and prepared["kind"] == "prepared-d4-binding", "Foreign D4 preparation")
    git_sha(prepared["expected_head"])
    event = binding_event(prepared["binding"], journal.config)
    require_purpose(prepared["binding"]["purpose"])
    require(canonical(frozen_source(root, journal)) == canonical(prepared["binding"]["source"]),
        "D4 candidate changed after preparation")
    snapshot = journal.read()
    require(snapshot["head"] == prepared["expected_head"], "D4 journal advanced after preparation; do not replay")
    return journal.anchor(journal.candidate(event, snapshot))
