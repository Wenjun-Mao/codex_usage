"""Fixed journal domains and strict records; pilot events are never production proof."""
import json
from pathlib import PurePosixPath
import re

from .policy import REPOSITORY, ROOT, SCHEMA, TARGETS, WORKFLOW, canonical, digest, positive, require

CONFIG = ROOT / "scripts/release/journal-origins.json"
FILE = "journal.json"
MAX_RECORDS = 10000
MAX_BLOB = 65536


def git_sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value), "Invalid Git object identity")
    return value


def configuration(domain, config=None, *, pinned=True):
    config = json.loads(CONFIG.read_text()) if config is None else config
    require(domain in ("production", "pilot") and type(config["schema"]) is int and config["schema"] == SCHEMA
        and config["repository"] == REPOSITORY, "Foreign journal configuration")
    expected = {"production": ("refs/heads/codex/publication-receipts", ".github/workflows/promote-vsix.yml"),
        "pilot": ("refs/heads/codex/publication-journal-pilot", ".github/workflows/journal-pilot.yml")}
    selected = config["domains"][domain]
    require((selected["ref"], selected["workflow"]) == expected[domain], "Foreign journal namespace")
    result = {**selected, "domain": domain, "repository_id": positive(config["repository_id"])}
    if pinned:
        git_sha(result["genesis"])
        positive(result["workflow_id"])
    return result


def origin(config):
    return {"schema": SCHEMA, "kind": "publication-journal-origin", "domain": config["domain"],
        "repository": REPOSITORY, "repository_id": config["repository_id"],
        "workflow": config["workflow"], "workflow_id": positive(config["workflow_id"]),
        "minimum_version": config["minimum_version"]}


def validate_event(event, config):
    domain = config["domain"]
    expected_kind = "publication-start" if domain == "production" else "synthetic-start"
    require(set(event) == {"schema", "kind", "domain", "workflow_id", "intent"}
        and type(event["schema"]) is int and event["schema"] == SCHEMA and event["kind"] == expected_kind
        and event["domain"] == domain and type(event["workflow_id"]) is int
        and event["workflow_id"] == config["workflow_id"], "Foreign journal event")
    data = event["intent"]
    fields = {"schema", "kind", "source", "tag", "qualification_run", "qualification_attempt", "manifest_sha256",
        "publisher_sha", "target", "package", "origin"}
    require(set(data) == fields and type(data["schema"]) is int and data["schema"] == SCHEMA
        and data["kind"] == ("publication-intent" if domain == "production" else "synthetic-journal-intent"), "Foreign intent contract")
    source = data["source"]
    require(set(source) == {"repository", "repository_id", "sha", "version", "contract", "workflow", "probe"}
        and source["repository"] == REPOSITORY and type(source["repository_id"]) is int
        and source["repository_id"] == config["repository_id"] and source["probe"] is (domain == "pilot")
        and source["workflow"] == (WORKFLOW if domain == "production" else config["workflow"]), "Foreign journal source")
    git_sha(source["sha"])
    digest(source["contract"])
    require(isinstance(source["version"], str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", source["version"])
        and data["tag"] == "v" + source["version"] and data["target"] in TARGETS, "Foreign release/target")
    if domain == "production":
        require(re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", source["version"])
            and tuple(map(int, source["version"].split("."))) >= tuple(map(int, config["minimum_version"].split("."))),
            "Production version predates the trusted journal cutover")
    for key in ("qualification_run", "qualification_attempt"):
        require(type(data[key]) is int, "Untyped qualification identity")
        positive(data[key])
    digest(data["manifest_sha256"])
    git_sha(data["publisher_sha"])
    writer = data["origin"]
    require(set(writer) == {"run", "attempt", "job"} and writer["job"] == ("publish" if domain == "production" else "pilot"),
        "Foreign journal writer")
    for key in ("run", "attempt"):
        require(type(writer[key]) is int, "Untyped writer identity")
        positive(writer[key])
    package = data["package"]
    require(set(package) == {"sha256", "bytes", "target", "version", "collector_sha256", "assets"}
        and package["target"] == data["target"] and package["version"] == source["version"], "Foreign package declaration")
    digest(package["sha256"])
    digest(package["collector_sha256"])
    require(type(package["bytes"]) is int, "Untyped package size")
    positive(package["bytes"])
    require(isinstance(package["assets"], dict) and 0 < len(package["assets"]) <= 1000, "Missing asset inventory")
    for name, value in package["assets"].items():
        path = PurePosixPath(name)
        require(name.startswith("extension/") and path.as_posix() == name and ".." not in path.parts
            and "\\" not in name and set(value) == {"sha256", "bytes"}, "Foreign asset path/inventory")
        digest(value["sha256"])
        require(type(value["bytes"]) is int and value["bytes"] >= 0, "Invalid asset size")
    require(len(canonical(event)) <= MAX_BLOB, "Journal event exceeds bounds")
    return event


def event_for(intent, config):
    return validate_event({"schema": SCHEMA, "kind": "publication-start" if config["domain"] == "production" else "synthetic-start",
        "domain": config["domain"], "workflow_id": config["workflow_id"], "intent": intent}, config)


def prior_targets(records, qualified):
    result = {}
    for record in records:
        intent = record["event"]["intent"]
        if intent["source"]["version"] != qualified["source"]["version"]:
            continue
        target = intent["target"]
        require(intent["source"]["sha"] == qualified["source"]["sha"]
            and canonical(intent["package"]) == canonical(qualified["manifest"]["packages"][target]),
            "Same-version retained intent conflicts with qualified source/package")
        result[target] = True
    return result
