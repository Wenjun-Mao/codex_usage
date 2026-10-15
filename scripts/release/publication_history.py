"""Trusted durable intents distinguish missing packages from catalog-invisible uploads."""
import json
import os
import re
import subprocess

from .policy import PROMOTION_WORKFLOW, ROOT, SCHEMA, TARGETS, canonical, contract_blobs, digest, positive, require
from .proofs import unique_job

PREFIX = "CODEX_PUBLICATION_INTENT "
CHECKOUT = "CODEX_PUBLISHER_CHECKOUT "


def markers(log, prefix):
    log = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", log)
    values = []
    for line in log.splitlines():
        match = re.fullmatch(r"(?:[0-9T:.Z+-]+\s+)?" + re.escape(prefix) + r"(.*)", line)
        if match:
            values.append(match[1])
    return values


def intent(qualified, target, env=os.environ):
    require(target in TARGETS and qualified["status"] == "validated-for-publication", "Intent lacks publication authority")
    require(env.get("GITHUB_REF") == "refs/tags/" + qualified["tag"], "Intent is not on the qualified tag")
    require(env.get("GITHUB_SHA") == qualified["source"]["sha"], "Intent dispatch source differs from qualification")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    require(qualified["promotion"] == {"run": positive(env["GITHUB_RUN_ID"]),
        "attempt": positive(env["GITHUB_RUN_ATTEMPT"]), "sha": qualified["source"]["sha"],
        "ref": env["GITHUB_REF"], "publisher_sha": head}, "Intent publication context differs")
    data = {"schema": SCHEMA, "kind": "publication-intent", "source": qualified["source"],
        "tag": qualified["tag"], "qualification_run": qualified["qualification_run"],
        "qualification_attempt": qualified["qualification_attempt"], "manifest_sha256": qualified["manifest_sha256"],
        "publisher_sha": head, "target": target, "package": qualified["manifest"]["packages"][target],
        "origin": {"run": positive(env["GITHUB_RUN_ID"]), "attempt": positive(env["GITHUB_RUN_ATTEMPT"]), "job": "publish"}}
    if "latency_binding" in qualified:
        data["latency_binding"] = qualified["latency_binding"]
    return data


def stamp(target, artifact_id, artifact_digest, env=os.environ):
    require(target in TARGETS, "Unknown publication target")
    return PREFIX + canonical({"target": target, "artifact_id": positive(artifact_id),
        "artifact_digest": digest(artifact_digest), "run": positive(env["GITHUB_RUN_ID"]),
        "attempt": positive(env["GITHUB_RUN_ATTEMPT"])}).decode().strip()


def original_successful_job(api, run_id, attempt, name):
    selected = unique_job(api.jobs(run_id, attempt), name)
    times = (selected["started_at"], selected["completed_at"])
    for origin in range(1, positive(attempt) + 1):
        matches = [job for job in api.jobs(run_id, origin) if job["name"] == name]
        require(len(matches) <= 1, "Ambiguous original job execution")
        if matches and (matches[0].get("started_at"), matches[0].get("completed_at")) == times:
            return unique_job(matches, name)
    raise ValueError("Missing original job execution")


def publisher_revision(api, run_id, attempt, blobs):
    validation = original_successful_job(api, run_id, attempt, "Validate qualification")
    revisions = markers(api.logs(validation["id"]), CHECKOUT)
    require(len(revisions) == 1 and re.fullmatch("[0-9a-f]{40}", revisions[0]), "Missing trusted publisher checkout marker")
    tree = api.contract_tree(revisions[0])
    require(blobs and all(tree.get(name) == value for name, value in blobs.items()), "Publisher execution closure differs")
    return revisions[0]


def prior_intents(api, qualified, current_run, current_attempt, blobs=None):
    """Diagnostic Actions inspection only; not complete side-effect authority."""
    blobs = contract_blobs(ROOT) if blobs is None else blobs
    # Source filtering would forget a possibly accepted upload after tag drift.
    endpoint = f"{api.prefix}/actions/workflows/promote-vsix.yml/runs"
    runs = api.pages(endpoint, "workflow_runs")
    current = api.run(positive(current_run))
    require(current["path"] == PROMOTION_WORKFLOW, "Foreign current promotion workflow")
    numbers = [positive(row["run_number"]) for row in runs]
    require(len(numbers) == len(set(numbers)), "Duplicate promotion run numbers")
    observed = {*numbers, positive(current["run_number"])}
    require(max(observed) <= 10000 and observed == set(range(1, max(observed) + 1)),
        "Missing promotion history; deleted or unavailable runs block automatic retry")
    possible, seen = {}, set()
    for summary in runs:
        run = api.run(summary["id"])
        require(run["path"] == PROMOTION_WORKFLOW and run["event"] == "workflow_dispatch"
            and run["head_repository"]["id"] == run["repository"]["id"], "Foreign publication history")
        if run["head_branch"] != qualified["tag"]:
            continue  # Credential-free inspection on main, not a publisher.
        require(run["head_sha"] == qualified["source"]["sha"], "Same release tag has conflicting dispatch source; retry blocked")
        for attempt in range(1, positive(run["run_attempt"]) + 1):
            if run["id"] == positive(current_run) and attempt >= positive(current_attempt):
                continue
            jobs = api.jobs(run["id"], attempt)
            publishers = [job for job in jobs if job["name"] == "Publish qualified packages"]
            require(len(publishers) <= 1, "Ambiguous prior publisher")
            if not publishers or publishers[0].get("conclusion") == "skipped":
                continue
            publisher = publishers[0]
            require(publisher.get("status") == "completed", "Another publisher is still running; remain pending")
            execution = (run["id"], publisher.get("started_at"), publisher.get("completed_at"))
            if execution in seen:
                continue
            revision = publisher_revision(api, run["id"], attempt, blobs)
            log_markers = [json.loads(value) for value in markers(api.logs(publisher["id"]), PREFIX)]
            require(len({value["target"] for value in log_markers}) == len(log_markers), "Duplicate publication intents")
            recorded = set()
            for marker in log_markers:
                target = marker["target"]
                require(target in TARGETS and marker["run"] == run["id"] and type(marker["attempt"]) is int
                    and positive(marker["attempt"]) <= attempt,
                    "Foreign intent origin")
                artifact, files = api.artifact(marker["artifact_id"], marker["artifact_digest"], run)
                require(artifact["name"] == f"intent-{target}-r{run['id']}-a{marker['attempt']}", "Foreign intent artifact name")
                require(set(files) == {"intent.json"}, "Foreign intent archive")
                record = json.loads(files["intent.json"])
                expected = {"schema": SCHEMA, "kind": "publication-intent", "source": qualified["source"],
                    "tag": qualified["tag"], "qualification_run": qualified["qualification_run"],
                    "qualification_attempt": qualified["qualification_attempt"], "manifest_sha256": qualified["manifest_sha256"],
                    "publisher_sha": revision, "target": target, "package": qualified["manifest"]["packages"][target],
                    "origin": {"run": run["id"], "attempt": marker["attempt"], "job": "publish"}}
                if "latency_binding" in qualified:
                    expected["latency_binding"] = qualified["latency_binding"]
                require(canonical(record) == canonical(expected), "Intent identity differs")
                original_jobs = api.jobs(run["id"], marker["attempt"])
                original = next(job for job in original_jobs if job["name"] == "Publish qualified packages")
                require((original.get("started_at"), original.get("completed_at")) ==
                    (publisher.get("started_at"), publisher.get("completed_at")), "Intent is not from original publisher execution")
                recorded.add(target)
                possible[target] = True
            for target in TARGETS:
                calls = [step for step in publisher.get("steps", []) if step["name"] == f"Publish {target}"]
                require(calls, "Unknown historical publisher step inventory")
                if any(step.get("conclusion") not in (None, "skipped") or step.get("status") == "in_progress" for step in calls):
                    require(target in recorded, "Unexplained prior upload; automatic retry blocked")
            seen.add(execution)
    return possible


def verify_complete(api, qualified, blobs=None, retained_reader=None):
    promotion = qualified["promotion"]
    run = api.run(promotion["run"])
    require(run.get("status") == "completed" and run.get("conclusion") == "success"
        and run["run_attempt"] == promotion["attempt"] and run["head_sha"] == qualified["source"]["sha"],
        "Promotion execution did not complete successfully")
    blobs = contract_blobs(ROOT) if blobs is None else blobs
    require(publisher_revision(api, run["id"], promotion["attempt"], blobs) == promotion["publisher_sha"],
        "Publisher revision differs from validated execution")
    publisher = original_successful_job(api, run["id"], promotion["attempt"], "Publish qualified packages")
    expected = {"qualification_run": qualified["qualification_run"], "qualification_attempt": qualified["qualification_attempt"],
        "source": qualified["source"], "packages": qualified["manifest"]["packages"]}
    if "latency_binding" in qualified:
        expected["latency_binding"] = qualified["latency_binding"]
    actual = [json.loads(value) for value in markers(api.logs(publisher["id"]), "CODEX_PROMOTION_COMPLETE ")]
    require(canonical(actual) == canonical([expected]), "Missing or ambiguous original publisher completion")
    from .git_journal import Journal
    from .journal_model import prior_targets
    snapshot = (retained_reader or Journal(api).read)()
    possible = prior_targets(snapshot["records"], qualified)
    return {"schema": SCHEMA, "promotion": promotion, "publisher_job_id": publisher["id"],
        "completed": expected, "prior_intents": possible}
