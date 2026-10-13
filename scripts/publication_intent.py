"""Prepare/stamp durable intent or inspect history before publisher credentials."""
import argparse
import json
import os
from pathlib import Path

from release.github import GitHub
from release.policy import PROMOTION_BLOCKER, PROMOTION_ENABLED, TARGETS, canonical, contract_blobs, require
from hashlib import sha256
from release.publication_history import intent, publisher_revision, stamp, verify_complete
from release.git_journal import Journal
from release.journal_api import JournalAPI
from release.journal_model import configuration, event_for, prior_targets


def writer_context(api, qualified):
    require(PROMOTION_ENABLED, PROMOTION_BLOCKER)
    selected = configuration("production")
    promotion = qualified["promotion"]
    require(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_JOB") == "publish",
        "Production journal requires the approved publisher job")
    run = api.run(promotion["run"])
    require(run["workflow_id"] == selected["workflow_id"] and run["path"] == selected["workflow"]
        and run["repository"]["id"] == selected["repository_id"] and run["head_repository"]["id"] == selected["repository_id"]
        and run["head_sha"] == qualified["source"]["sha"] and run["head_branch"] == qualified["tag"]
        and run["run_attempt"] == promotion["attempt"] and run["event"] == "workflow_dispatch", "Foreign journal writer dispatch")
    require(publisher_revision(api, run["id"], promotion["attempt"], contract_blobs()) == promotion["publisher_sha"],
        "Journal writer execution closure differs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "stamp", "history", "verify-complete"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--target", choices=TARGETS)
    parser.add_argument("--artifact-id")
    parser.add_argument("--artifact-digest")
    args = parser.parse_args()
    qualified = json.loads((args.directory / "qualified.json").read_text())
    if args.command == "history":
        # Git history, not surviving Actions runs, is the retained side-effect authority.
        data = prior_targets(Journal(JournalAPI("production")).read()["records"], qualified)
        (args.directory / "prior-intents.json").write_bytes(canonical(data))
    elif args.command == "verify-complete":
        (args.directory / "publisher-proof.json").write_bytes(canonical(verify_complete(GitHub(), qualified)))
    elif args.command == "prepare":
        api = JournalAPI("production")
        writer_context(api, qualified)
        data = intent(qualified, args.target)
        journal = Journal(api)
        receipt = journal.anchor(journal.candidate(event_for(data, journal.config)))
        destination = args.directory / f"intent-{args.target}"
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "intent.json").write_bytes(canonical(data))
        (args.directory / f"intent-{args.target}-journal.json").write_bytes(canonical(receipt))
    else:
        body = (args.directory / f"intent-{args.target}/intent.json").read_bytes()
        if json.loads(body) != intent(qualified, args.target):
            raise ValueError("Persisted intent differs from current publication context")
        api = JournalAPI("production")
        writer_context(api, qualified)
        receipt = json.loads((args.directory / f"intent-{args.target}-journal.json").read_text())
        actual = Journal(api).witness(receipt["commit"], json.loads(body))
        require(canonical(receipt) == canonical(actual), "Retained journal acknowledgement differs")
        message = stamp(args.target, args.artifact_id, args.artifact_digest)
        (args.directory / f"intent-{args.target}-ack.json").write_bytes(canonical({
            "target": args.target, "artifact_id": args.artifact_id, "artifact_digest": args.artifact_digest,
            "run": qualified["promotion"]["run"], "attempt": qualified["promotion"]["attempt"],
            "intent_sha256": sha256(body).hexdigest(), "journal": receipt}))
        binding = {"schema": 1, "source": qualified["source"], "tag": qualified["tag"], "promotion": qualified["promotion"],
            "qualification_run": qualified["qualification_run"], "qualification_attempt": qualified["qualification_attempt"],
            "manifest_sha256": qualified["manifest_sha256"], "target": args.target,
            "package_sha256": qualified["manifest"]["packages"][args.target]["sha256"],
            "intent_sha256": sha256(body).hexdigest(), "journal": receipt}
        (args.directory / f"intent-{args.target}-authority.json").write_bytes(canonical(binding))
        print(message)


if __name__ == "__main__":
    main()
