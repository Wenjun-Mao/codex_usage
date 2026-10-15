"""Structural D4 records; only independently retained history grants authority."""
from copy import deepcopy
import re
from uuid import UUID

from .journal_model import git_sha
from .policy import REPOSITORY, SCHEMA, WORKFLOW, canonical, digest, fingerprint, positive, require

KIND = "d4-latency-binding"
EXCEPTION_ID = "next-release-hosted-webkit-latency-2026-10"
MAX_BINDINGS = 4
SOURCE_FIELDS = frozenset(("repository", "repository_id", "sha", "version", "contract", "workflow"))
SCOPE = {"suite": "hover", "engine": "webkit", "execution": "hosted",
    "phases": ["hover", "hide", "keyboard"], "disposition": "deferred-known-latency",
    "strict_seconds": .25, "functional_seconds": 2.0, "process_seconds": 600}


def version(value):
    require(isinstance(value, str) and len(value) <= 64
        and re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value),
        "Invalid D4 release version")
    return tuple(map(int, value.split(".")))


def validate_binding(binding, config):
    require(config["domain"] == "production" and isinstance(binding, dict)
        and set(binding) == {"slot", "revision", "supersedes", "purpose", "source", "approval"},
        "Foreign D4 binding contract")
    slot = binding["slot"]
    require(isinstance(slot, dict) and set(slot) == {"id", "release_version", "max_bindings", "scope"}
        and slot["id"] == EXCEPTION_ID and type(slot["max_bindings"]) is int
        and slot["max_bindings"] == MAX_BINDINGS and canonical(slot["scope"]) == canonical(SCOPE),
        "Foreign D4 release slot or observation scope")
    require(version(slot["release_version"]) >= version(config["minimum_version"]),
        "D4 release predates the trusted cutover")
    require(type(binding["revision"]) is int and 1 <= binding["revision"] <= MAX_BINDINGS,
        "D4 binding revision exceeds its approved bound")
    if binding["supersedes"] is not None:
        git_sha(binding["supersedes"])
    require(binding["purpose"] in ("nonpublishing", "release"), "Unknown D4 binding purpose")
    source = binding["source"]
    require(isinstance(source, dict) and set(source) == SOURCE_FIELDS
        and source["repository"] == REPOSITORY and type(source["repository_id"]) is int
        and source["repository_id"] == config["repository_id"] and source["workflow"] == WORKFLOW,
        "Foreign D4 source identity")
    git_sha(source["sha"])
    digest(source["contract"])
    require(version(source["version"]) <= version(slot["release_version"]),
        "D4 source version exceeds its reserved release")
    require(binding["purpose"] != "release" or source["version"] == slot["release_version"],
        "D4 release source does not match the reserved version")
    require(isinstance(binding["approval"], str) and binding["approval"].strip()
        and len(binding["approval"]) <= 2000
        and "\x00" not in binding["approval"], "D4 binding requires explicit approval/reason")
    return binding


def binding_event(binding, config):
    return {"schema": SCHEMA, "kind": KIND, "domain": config["domain"],
        "workflow_id": config["workflow_id"], "binding": deepcopy(validate_binding(binding, config))}


def reference(record, config):
    require(record["event"]["kind"] == KIND, "Not a D4 binding record")
    return {"schema": SCHEMA, "domain": config["domain"], "ref": config["ref"],
        "genesis": config["genesis"], "commit": record["commit"], "sequence": record["sequence"],
        "invocation": record["invocation"], "binding_sha256": fingerprint(record["event"]["binding"])}


def validate_reference(value, config):
    require(isinstance(value, dict) and set(value) == {"schema", "domain", "ref", "genesis",
        "commit", "sequence", "invocation", "binding_sha256"}
        and type(value["schema"]) is int and value["schema"] == SCHEMA
        and value["domain"] == "production" and config["domain"] == "production"
        and value["ref"] == config["ref"] and value["genesis"] == config["genesis"],
        "Foreign D4 binding reference")
    git_sha(value["commit"])
    require(type(value["sequence"]) is int, "Untyped D4 sequence")
    positive(value["sequence"])
    invocation = value["invocation"]
    require(isinstance(invocation, str) and UUID(invocation).version == 4
        and str(UUID(invocation)) == invocation, "Invalid D4 invocation")
    digest(value["binding_sha256"])
    return value


def require_source(binding, source, *, publication=False):
    # Fault-injection is run context, not code identity. Such runs remain
    # ineligible for publication under the independent qualification contract.
    require(isinstance(source, dict) and set(source) == SOURCE_FIELDS | {"probe"}
        and type(source["probe"]) is bool
        and canonical({key: source[key] for key in SOURCE_FIELDS}) == canonical(binding["source"]),
        "D4 binding authorizes another source/version/contract")
    require(not publication or (binding["purpose"] == "release" and source["probe"] is False),
        "Nonpublishing D4 binding cannot authorize publication")


def require_current(record, source, *, publication=False):
    require(record is not None, "Missing current D4 candidate binding")
    require_source(record["event"]["binding"], source, publication=publication)
    return record
