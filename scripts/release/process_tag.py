"""Non-forced tag publication with durable intent and remote reconciliation."""
from .policy import require
from .process_candidate import git
from .process_state import Pending, command, now


def remote_tag(api, tag):
    # ls-remote distinguishes a missing ref from network/permission errors.
    rows = git("ls-remote", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    if not rows:
        return None
    values = dict(row.split()[::-1] for row in rows.splitlines())
    return values.get(f"refs/tags/{tag}^{{}}", values.get(f"refs/tags/{tag}"))


def ensure_tag(progress, api, *, allow=False, run_command=command):
    tag = "v" + progress.candidate["version"]
    sha = progress.candidate["sha"]
    remote = remote_tag(api, tag)
    if remote is not None:
        require(remote == sha, "Published tag differs; never move or force it")
        return tag
    if progress.data["operations"].get("tag"):
        raise Pending("Tag push was attempted but is not visible; reconcile without repeating it")
    if not allow:
        raise Pending("Explicit promote mode is required to create the tag")
    local = git("tag", "--list", tag)
    if local:
        require(git("rev-parse", f"refs/tags/{tag}^{{commit}}") == sha, "Local tag differs")
    progress.data["operations"]["tag"] = {"tag": tag, "sha": sha, "created_at": now()}
    progress.save()
    try:
        if not local:
            run_command(["git", "tag", tag, sha])
        run_command(["git", "push", "origin", f"refs/tags/{tag}:refs/tags/{tag}"])
    except Exception:
        raise Pending("Tag reply unknown; read back the exact remote tag without repeating the push") from None
    require(remote_tag(api, tag) == sha, "Tag push did not produce exact qualified source")
    return tag
