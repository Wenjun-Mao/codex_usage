"""Bind on-demand release work to the retained checkout and actual inputs."""
from hashlib import sha256
import json
import re

from .policy import ROOT, REPOSITORY, contract_identity, package_version, require
from .process_state import command


def git(*args, root=ROOT, raw=False):
    return command(["git", *args], root=root, capture=True, timeout=90, strip=not (raw or "-z" in args))


def candidate(*, root=ROOT, allow_receipt_edits=False):
    require(git("branch", "--show-current", root=root) == "main", "Use retained main, not an implicit worktree")
    dirty = git("diff", "HEAD", "--name-only", "--", root=root).splitlines()
    allowed = {"docs/release.md", "docs/release/qualified-promotion.md"} if allow_receipt_edits else set()
    require(set(dirty) <= allowed, "Commit tracked candidate changes first")
    remote = git("remote", "get-url", "origin", root=root)
    require(remote in (f"https://github.com/{REPOSITORY}.git", f"git@github.com:{REPOSITORY}.git"),
        "Unexpected origin")
    untracked = git("ls-files", "--others", "--exclude-standard", root=root).splitlines()
    require(not any(p.startswith(("src/", "scripts/", "tests/", ".github/", "extensions/vscode/"))
        for p in untracked), "Stage/commit new executable, test or extension inputs first")
    return {"repository": REPOSITORY, "sha": git("rev-parse", "HEAD", root=root),
        "version": package_version(root), "contract": contract_identity(root)}


def unchanged(expected, *, root=ROOT):
    require(candidate(root=root) == expected, "Candidate changed while release work was running")


def inputs(root=ROOT):
    """Hash actual tracked worktree bytes, including staged additions/deletions."""
    untracked = git("ls-files", "--others", "--exclude-standard", root=root).splitlines()
    require(not any(p.startswith(("src/", "scripts/", "tests/", ".github/", "extensions/vscode/"))
        for p in untracked), "Stage new candidate code/tests before local preflight")
    names = git("ls-files", "-z", root=root).split("\0")
    result = {}
    for name in sorted(set(filter(None, names))):
        path = root / name
        require(not path.is_symlink(), f"Symlinked release input: {name}")
        result[name] = sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return result


def changes(base, root=ROOT):
    require(re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", base) is not None, "Choose an explicit release base tag")
    sha = git("rev-parse", "--verify", f"refs/tags/{base}^{{commit}}", root=root)
    git("merge-base", "--is-ancestor", sha, "HEAD", root=root)
    # --no-renames includes both old and new paths, avoiding a rename selection hole.
    names = git("diff", "--no-renames", "--name-only", "-z", sha, "--", root=root).split("\0")
    return sha, sorted(set(filter(None, names)))


def assert_remote_main(api, expected):
    record = json.loads(api.raw(f"{api.prefix}/git/ref/heads/main"))
    require(record["object"]["sha"] == expected["sha"], "Push exact candidate to main before dispatch")
