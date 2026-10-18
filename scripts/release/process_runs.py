"""Correlated, once-only workflow dispatch and one bounded run observer."""
import json
from time import monotonic, sleep
from urllib.parse import urlencode
from uuid import UUID, uuid4

from .policy import REPOSITORY, WORKFLOW, PROMOTION_WORKFLOW, positive, require
from .process_state import Pending, command, now


def request_id(value, *, optional=False):
    if optional and value == "":
        return value
    require(isinstance(value, str) and str(UUID(value)) == value and UUID(value).version == 4,
        "Correlation must be a canonical UUID4")
    return value


def fresh_run(api, run_id):
    return json.loads(api.raw(f"{api.prefix}/actions/runs/{positive(run_id)}"))


def validate_run(run, operation, candidate):
    require(run.get("repository", {}).get("full_name") == REPOSITORY
        and run.get("head_repository", {}).get("id") == run["repository"]["id"]
        and run.get("event") == "workflow_dispatch" and run.get("path") == operation["workflow"]
        and run.get("head_sha") == candidate["sha"] and run.get("head_branch") == operation["ref"]
        and positive(run.get("run_attempt")) == 1, "Run source/repository/workflow/ref/attempt differs")
    token = request_id(operation["request_id"])
    if operation["workflow"] == WORKFLOW:
        title = f"Qualify Codex Usage VSIX ref={operation['ref']} probe=false request={token}"
    else:
        fields = operation["fields"]
        require(set(fields) == {"qualification_run", "qualification_attempt", "dry_run"}
            and fields["dry_run"] in ("true", "false"), "Unexpected promotion inputs")
        title = (f"Promote qualified run={positive(fields['qualification_run'])} "
            f"attempt={positive(fields['qualification_attempt'])} dry-run={fields['dry_run']} request={token}")
    require(run.get("display_title") == title,
        "Run correlation differs")
    positive(run["id"])
    return run


def discover(api, operation, candidate):
    query = urlencode({"event": "workflow_dispatch", "head_sha": candidate["sha"],
        "branch": operation["ref"], "created": ">=" + operation["created_at"][:10], "per_page": 100})
    rows, total = [], None
    for page in range(1, 11):
        data = json.loads(api.raw(f"{api.prefix}/actions/runs?{query}&page={page}"))
        require(type(data.get("total_count")) is int and data["total_count"] <= 1000, "Excessive dispatch search")
        total = data["total_count"]
        rows.extend(data["workflow_runs"])
        if len(data["workflow_runs"]) < 100:
            break
    require(len({r["id"] for r in rows}) == len(rows) and len(rows) == total,
        "Dispatch search changed or is incomplete; reconcile without redispatch")
    matches = [r for r in rows if r.get("display_title", "").endswith(" request=" + operation["request_id"])]
    require(len(matches) <= 1, "Multiple correlated runs; reconcile without redispatch")
    return validate_run(matches[0], operation, candidate) if matches else None


def observe(api, operation, candidate, *, seconds=1800, poll=10, clock=monotonic, wait=sleep):
    require(0 < seconds <= 3600 and 0 < poll <= 30, "Observer needs a finite bounded policy")
    deadline = clock() + seconds
    while True:
        run = fresh_run(api, operation["run"]) if operation.get("run") else discover(api, operation, candidate)
        if run is not None:
            validate_run(run, operation, candidate)
            operation["run"] = run["id"]
            if run["status"] == "completed":
                require(run["conclusion"] == "success", f"Workflow {run['id']} ended {run['conclusion']}; inspect diagnostics")
                return run
        if clock() >= deadline:
            raise Pending("Workflow pending or dispatch unacknowledged; resume observation, do not redispatch")
        wait(min(poll, max(0, deadline - clock())))


def dispatch(progress, api, name, *, workflow, ref, fields=None, allow=False, run_command=command):
    require(workflow in (WORKFLOW, PROMOTION_WORKFLOW), "Unexpected workflow")
    existing = progress.data["operations"].get(name)
    expected = {"workflow": workflow, "ref": ref, "fields": fields or {}}
    if existing:
        require(all(existing.get(k) == v for k, v in expected.items()), "Saved dispatch differs")
        request_id(existing["request_id"])
        return existing
    if not allow:
        raise Pending("No recorded dispatch; explicit prepare/promote mode required")
    if fields and fields.get("dry_run") == "false":
        query = urlencode({"event": "workflow_dispatch", "head_sha": progress.candidate["sha"],
            "branch": ref, "per_page": 100})
        runs = api.pages(f"{api.prefix}/actions/runs?{query}", "workflow_runs")
        require(not any(r.get("path") == workflow and " dry-run=false" in r.get("display_title", "")
            for r in runs), "A publication dispatch already exists; reconcile it instead of redispatching")
    operation = {**expected, "request_id": str(uuid4()), "created_at": now()}
    progress.data["operations"][name] = operation
    # Persist before the call: interruption, timeout and rejected replies never permit redelivery.
    progress.save()
    args = ["gh", "workflow", "run", workflow.rsplit("/", 1)[-1], "--repo", REPOSITORY,
        "--ref", ref, "--raw-field", "request_id=" + operation["request_id"]]
    for key, value in sorted(operation["fields"].items()):
        args.extend(["--field" if key == "dry_run" else "--raw-field", f"{key}={value}"])
    try:
        run_command(args, capture=True, timeout=120)
    except Exception:
        raise Pending("Dispatch response unknown; intent retained, reconcile the UUID without redispatch") from None
    return operation


def finish(progress, api, name, *, seconds):
    operation = progress.data["operations"][name]
    with progress.phase(name + "-observation"):
        run = observe(api, operation, progress.candidate, seconds=seconds)
    operation.update(run=run["id"], attempt=run["run_attempt"])
    progress.save()
    return run
