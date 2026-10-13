"""Promotion authority rejects incomplete and mismatched remote proof."""
from copy import deepcopy
import json
from stat import S_IFLNK
from zipfile import ZipInfo, ZipFile
from io import BytesIO

import pytest

from qualification_fixture import FixtureAPI, archives, package_bytes, policy, zip_bytes
from release_tooling_support import load_tool

check_release_tag = load_tool("qualification").check_release_tag
check_promotion_dispatch = load_tool("qualification").check_promotion_dispatch


def test_complete_producer_graph_and_frozen_hosted_identity():
    api = FixtureAPI()
    reader = api.reader()
    manifest = reader.freeze()
    assert set(manifest["gates"]) == set(policy.GATES)
    assert set(manifest["packages"]) == set(policy.TARGETS)
    api.add_gate("hosted", {"hosted.json": policy.canonical(manifest)})
    _, actual = api.reader().hosted()
    assert actual == manifest


@pytest.mark.parametrize("fault", [None, "source", "event", "workflow", "repository", "fork", "tag", "attempt", "context"])
def test_immutable_promotion_dispatch_must_match_qualification_before_credentials(fault):
    api = FixtureAPI()
    run = {**api.run_data, "id": 88, "path": policy.PROMOTION_WORKFLOW, "head_branch": "v2.12.2"}
    api.run = lambda identifier: run
    env = {"GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "88", "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": api.source["sha"], "GITHUB_REF": "refs/tags/v2.12.2"}
    if fault == "source":
        run["head_sha"] = "c" * 40
    elif fault == "event":
        run["event"] = "push"
    elif fault == "workflow":
        run["path"] = policy.WORKFLOW
    elif fault == "repository":
        run["repository"] = {"full_name": "foreign/repository", "id": 123}
    elif fault == "fork":
        run["head_repository"] = {"id": 999}
    elif fault == "tag":
        run["head_branch"] = "v2.12.1"
    elif fault == "attempt":
        run["run_attempt"] = 2
    elif fault == "context":
        env["GITHUB_SHA"] = "c" * 40
    if fault:
        with pytest.raises(ValueError):
            check_promotion_dispatch(api, api.source, "refs/tags/v2.12.2", 88, 1, env)
    else:
        assert check_promotion_dispatch(api, api.source, "refs/tags/v2.12.2", 88, 1, env)["sha"] == api.source["sha"]


def test_claimed_contract_digest_cannot_replace_source_git_blob_authority():
    api = FixtureAPI()
    expected = api.blobs.copy()
    api.blobs[policy.WORKFLOW] = "c" * 40
    with pytest.raises(ValueError, match="source Git tree"):
        load_tool("release.proofs").Proofs(api, 77, 1, api.source["contract"], api.source["version"], expected)


def test_terminal_escape_codes_do_not_defeat_original_log_validation():
    api = FixtureAPI()
    key = f"{api.prefix}/actions/jobs/{api.job_rows['visual-hover']['id']}/logs"
    api.bodies[key] = b"\x1b[32m" + api.bodies[key].rstrip() + b"\x1b[0m\n"
    assert api.reader().resolve("visual-hover")["originating_attempt"] == 1


def test_copied_attempt_records_are_not_origin_executions():
    api = FixtureAPI()
    copied = deepcopy(api.jobs_by_attempt[1])
    for job in copied:
        job.update(id=job["id"] + 100, run_attempt=2)
    api.jobs_by_attempt[2] = copied
    api.run_data["run_attempt"] = 2
    api._cache.clear()
    proof = api.reader().resolve("package-win32-x64", payload=True)
    assert proof["originating_attempt"] == 1
    assert proof["selected_job_id"] != proof["producer_job_id"]
    assert proof["receipt"]["origin"]["attempt"] == 1
    copied[3]["started_at"] = "2026-10-13T01:00:00Z"
    api._cache.clear()
    with pytest.raises(ValueError, match="Stale producer"):
        api.reader().resolve("package-win32-x64")


@pytest.mark.parametrize("field,value", [("event", "pull_request"), ("path", "other.yml"),
    ("head_branch", "fork"), ("conclusion", "failure"), ("status", "in_progress"), ("run_attempt", 2)])
def test_wrong_event_workflow_ref_or_run_state(field, value):
    api = FixtureAPI()
    api.run_data[field] = value
    api._cache.clear()
    with pytest.raises(ValueError):
        load_tool("release.proofs").Proofs(api, 77, 1, api.source["contract"], api.source["version"], api.blobs)


@pytest.mark.parametrize("state", ["failure", "skipped", "cancelled", "neutral"])
def test_mandatory_job_cannot_be_failed_or_skipped(state):
    api = FixtureAPI()
    api.job_rows["visual-hover"]["conclusion"] = state
    with pytest.raises(ValueError, match="Unsuccessful"):
        api.reader().freeze()


@pytest.mark.parametrize("fault", ["repo", "sha", "version", "contract", "workflow", "schema",
    "origin-attempt", "origin-run", "origin-job", "origin-key", "missing-assertion", "duplicate-case"])
def test_receipt_content_is_not_caller_authority(fault):
    api = FixtureAPI()
    def change(receipt):
        fields = {"repo": ("repository", "foreign/repo"), "sha": ("sha", "c"*40),
            "version": ("version", "9.9.9"), "contract": ("contract", "c"*64), "workflow": ("workflow", "other.yml")}
        if fault in fields:
            key, value = fields[fault]
            receipt["source"] = {**receipt["source"], key: value}
        elif fault == "schema":
            receipt["schema"] = 2
        elif fault.startswith("origin-"):
            key = {"origin-attempt": "attempt", "origin-run": "run", "origin-job": "job_name", "origin-key": "job_key"}[fault]
            receipt["origin"][key] = 2 if key == "attempt" else 88 if key == "run" else "other"
        elif fault == "missing-assertion":
            receipt["manifest"]["visual"]["hover"]["assertions"].pop()
        else:
            rows = receipt["manifest"]["visual"]["hover"]["completed"]
            rows[-1] = deepcopy(rows[0])
    api.rewrite_receipt("visual-hover", change)
    with pytest.raises(ValueError):
        api.reader().resolve("visual-hover", payload=True)


@pytest.mark.parametrize("fault", ["expired", "digest", "download", "repo", "run", "sha", "size", "missing-log", "duplicate-log", "missing-payload"])
def test_transport_and_original_job_association_fail_closed(fault):
    api = FixtureAPI()
    row = next(row for row in api.uploads if row["name"].startswith("receipt-visual-hover-"))
    if fault == "expired":
        row["expired"] = True
    elif fault == "digest":
        row["digest"] = "sha256:" + "0"*64
    elif fault == "download":
        api.bodies[f"{api.prefix}/actions/artifacts/{row['id']}/zip"] += b"changed"
    elif fault in ("repo", "run", "sha"):
        key = {"repo": "repository_id", "run": "id", "sha": "head_sha"}[fault]
        row["workflow_run"][key] = "c"*40 if fault == "sha" else 999
    elif fault == "size":
        row["size_in_bytes"] += 1
    elif fault == "missing-payload":
        api.uploads[:] = [row for row in api.uploads if not row["name"].startswith("payload-visual-hover-")]
    else:
        key = f"{api.prefix}/actions/jobs/{api.job_rows['visual-hover']['id']}/logs"
        api.bodies[key] = b"no marker" if fault == "missing-log" else api.bodies[key]*2
    with pytest.raises(ValueError):
        api.reader().resolve("visual-hover", payload=True)


def test_frozen_reference_cannot_omit_a_gate_or_substitute_a_receipt():
    api = FixtureAPI()
    manifest = api.reader().freeze()
    manifest["gates"].pop("metadata")
    api.add_gate("hosted", {"hosted.json": policy.canonical(manifest)})
    with pytest.raises(ValueError, match="incomplete hosted"):
        api.reader().hosted()


@pytest.mark.parametrize("fault", ["target", "publisher", "version", "collector", "xml", "assets"])
def test_vsix_identity_is_the_package_not_a_filename(fault):
    files = archives.zip_files(package_bytes())
    manifest = json.loads(files["extension/package.json"])
    if fault in ("publisher", "version"):
        manifest[fault] = "wrong"
        files["extension/package.json"] = policy.canonical(manifest)
    elif fault == "target":
        files["extension/bin/win32-x64/codex-usage-agent.exe"] = files.pop(archives.AGENTS["darwin-arm64"])
    elif fault == "collector":
        files["extension/bin/another-agent"] = b"foreign"
    elif fault == "xml":
        files["extension.vsixmanifest"] = files["extension.vsixmanifest"].replace(b'darwin-arm64', b'win32-x64')
    else:
        files.pop("extension/out/extension.js")
    with pytest.raises(ValueError):
        archives.package_identity(zip_bytes(files), "darwin-arm64", "2.12.2")


@pytest.mark.parametrize("name", ["../escape", "/absolute", "extension/../escape", "extension//escape", "extension/./escape", "C:\\escape"])
def test_unsafe_zip_paths_are_rejected(name):
    with pytest.raises(ValueError, match="Unsafe ZIP"):
        archives.zip_files(zip_bytes({name: b"unsafe"}))


def test_symlinks_and_duplicate_archive_paths_are_rejected():
    raw = BytesIO()
    with ZipFile(raw, "w") as archive:
        entry = ZipInfo("extension/symlink")
        entry.external_attr = (S_IFLNK | 0o777) << 16
        archive.writestr(entry, b"../../owner-data")
    with pytest.raises(ValueError):
        archives.zip_files(raw.getvalue())


def test_release_tag_peeling_and_main_ancestry_are_independent():
    api = FixtureAPI()
    source = api.source
    api.responses[f"{api.prefix}/git/ref/tags/v2.12.2"] = {"object": {"type": "tag", "sha": "d"*40}}
    api.responses[f"{api.prefix}/git/tags/{'d'*40}"] = {"object": {"type": "commit", "sha": source["sha"]}}
    api.responses[f"{api.prefix}/compare/{source['sha']}...main"] = {"merge_base_commit": {"sha": source["sha"]}, "status": "ahead"}
    assert check_release_tag(api, source, "refs/tags/v2.12.2") == "v2.12.2"
    with pytest.raises(ValueError):
        check_release_tag(api, source, "refs/heads/main")
    api.responses[f"{api.prefix}/git/tags/{'d'*40}"]["object"]["sha"] = "e"*40
    api._cache.clear()
    with pytest.raises(ValueError, match="peel"):
        check_release_tag(api, source, "refs/tags/v2.12.2")


@pytest.mark.parametrize("value", [True, False, 0, -1, "1.5", "1;unsafe", "", "001"])
def test_untrusted_identifiers_are_not_shell_or_number_coercions(value):
    with pytest.raises(ValueError):
        policy.positive(value)
