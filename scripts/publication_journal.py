"""Explicit bootstrap and nonpublishing hosted journal pilot; never Marketplace I/O."""
import argparse
import base64
import json
import os
from pathlib import Path

from release.git_journal import Journal, blob_sha
from release.journal_api import GitWriteError, JournalAPI
from release.journal_model import FILE, configuration, event_for, origin
from release.policy import REPOSITORY, SCHEMA, TARGETS, canonical, contract_identity, fingerprint, positive, require


def bootstrap(domain, output):
    api = JournalAPI(domain, bootstrap=True)
    selected = api.config
    require(selected["genesis"] is None and selected["workflow_id"] is None, "Bootstrap cannot reset pinned history")
    refs = api.json(f"{api.prefix}/git/matching-refs/{selected['ref'].removeprefix('refs/')}")
    require(not any(row["ref"] == selected["ref"] for row in refs), "Journal ref already exists; do not overwrite/reinitialize")
    repo = api.json(api.prefix)
    require(repo["id"] == selected["repository_id"] and repo["full_name"] == REPOSITORY, "Foreign repository origin")
    workflow = api.json(f"{api.prefix}/actions/workflows/{selected['workflow'].rsplit('/', 1)[1]}")
    require(workflow["path"] == selected["workflow"] and workflow["state"] == "active", "Foreign/disabled journal workflow")
    selected["workflow_id"] = positive(workflow["id"])
    data = canonical(origin(selected))
    blob = api.write("POST", "git/blobs", {"content": base64.b64encode(data).decode(), "encoding": "base64"})
    require(blob["sha"] == blob_sha(data), "Bootstrap blob identity differs")
    tree = api.write("POST", "git/trees", {"tree": [{"path": FILE, "mode": "100644", "type": "blob", "sha": blob["sha"]}]})
    commit = api.write("POST", "git/commits", {"message": f"Initialize {domain} publication journal", "tree": tree["sha"], "parents": []})
    selected["genesis"] = commit["sha"]
    api.write("POST", "git/refs", {"ref": selected["ref"], "sha": selected["genesis"]})
    config = json.loads(Path(__file__).with_name("release").joinpath("journal-origins.json").read_text())
    config["domains"][domain].update(genesis=selected["genesis"], workflow_id=selected["workflow_id"])
    Journal(api, domain, config).read()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical({"domain": domain, "genesis": selected["genesis"], "workflow_id": selected["workflow_id"],
        "ref": selected["ref"], "origin": origin(selected)}))


def pilot(output):
    require(not os.environ.get("VSCE_PAT") and os.environ.get("GITHUB_REF") == "refs/heads/main"
        and os.environ.get("GITHUB_JOB") == "pilot", "Synthetic pilot context only; no publisher credentials")
    api = JournalAPI("pilot")
    selected = configuration("pilot")
    run = api.run(positive(os.environ["GITHUB_RUN_ID"]))
    require(run["workflow_id"] == selected["workflow_id"] and run["path"] == selected["workflow"]
        and run["head_sha"] == os.environ["GITHUB_SHA"] and run["repository"]["id"] == selected["repository_id"]
        and run["event"] == "workflow_dispatch" and run["head_branch"] == "main", "Foreign pilot dispatch")
    version = f"0.0.0-pilot.r{run['id']}.a{os.environ['GITHUB_RUN_ATTEMPT']}"
    source = {"repository": REPOSITORY, "repository_id": selected["repository_id"], "sha": run["head_sha"],
        "version": version, "contract": contract_identity(), "workflow": selected["workflow"], "probe": True}
    events = []
    for target in TARGETS:
        package = {"sha256": fingerprint({"synthetic": target}), "bytes": 17, "target": target, "version": version,
            "collector_sha256": fingerprint({"synthetic_collector": target}),
            "assets": {"extension/out/synthetic.js": {"sha256": fingerprint({"asset": target}), "bytes": 17}}}
        data = {"schema": SCHEMA, "kind": "synthetic-journal-intent", "source": source, "tag": "v"+version,
            "qualification_run": run["id"], "qualification_attempt": positive(os.environ["GITHUB_RUN_ATTEMPT"]),
            "manifest_sha256": fingerprint({"synthetic_manifest": version}), "publisher_sha": source["sha"],
            "target": target, "package": package, "origin": {"run": run["id"],
                "attempt": positive(os.environ["GITHUB_RUN_ATTEMPT"]), "job": "pilot"}}
        events.append(event_for(data, selected))
    journal = Journal(api, "pilot")
    before = journal.read()
    winner, stale = [journal.candidate(event, before) for event in events]
    first = journal.anchor(winner)
    # Probe the server's fast-forward condition directly, not just the local read guard.
    lost = False
    try:
        api.write("PATCH", "git/refs/" + selected["ref"].removeprefix("refs/"), {"sha": stale["commit"], "force": False})
    except GitWriteError as error:
        require(str(error.status) in ("409", "422"), "Unexpected pilot write error")
        lost = True
    require(lost, "Stale sibling unexpectedly advanced the retained journal")
    second = journal.anchor(journal.candidate(events[1]))
    replay_blocked = False
    try:
        journal.candidate(events[0])
    except ValueError:
        replay_blocked = True
    require(replay_blocked, "Replay unexpectedly created new authority")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical({"schema": SCHEMA, "synthetic_only": True, "domain": "pilot", "first": first,
        "second": second, "stale_sibling_rejected": lost, "replay_rejected": replay_blocked,
        "publication_calls": 0, "production_journal_writes": 0}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("bootstrap")
    init.add_argument("--domain", choices=("production", "pilot"), required=True)
    init.add_argument("--output", type=Path, required=True)
    probe = commands.add_parser("pilot")
    probe.add_argument("--output", type=Path, required=True)
    prepare = commands.add_parser("prepare-latency-binding")
    prepare.add_argument("--release-version", required=True)
    prepare.add_argument("--purpose", choices=("nonpublishing", "release"), required=True)
    prepare.add_argument("--approval", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    append = commands.add_parser("append-latency-binding")
    append.add_argument("--prepared", type=Path, required=True)
    append.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "bootstrap":
        bootstrap(args.domain, args.output)
    elif args.command == "pilot":
        pilot(args.output)
    else:
        from release import latency_admin
        if args.command == "prepare-latency-binding":
            result = latency_admin.prepare(args.release_version, args.purpose, args.approval)
        else:
            result = latency_admin.append(json.loads(args.prepared.read_text()))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical(result))


if __name__ == "__main__":
    main()
