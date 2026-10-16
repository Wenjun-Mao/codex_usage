from copy import deepcopy

import pytest

from qualification_fixture import archives, collector_proof, package_bytes, policy
from release_tooling_support import load_tool

validate = load_tool("release.collector_proof").validate_collector_proof


@pytest.mark.parametrize("target", policy.TARGETS)
def test_collector_proof_binds_target_bytes_and_real_overlap(target):
    package = archives.package_identity(package_bytes(target), target, "2.12.2")
    proof = collector_proof(target)
    assert validate({"collector-parallel.json": policy.canonical(proof)}, package) == proof


@pytest.mark.parametrize("field,value", [
    ("collector_sha256", "a"*64), ("oracle_equal", False), ("append_events", 0),
    ("unchanged_source_bytes", 1), ("contract", "old-smoke"),
])
def test_collector_proof_rejects_incomplete_or_foreign_execution(field, value):
    proof = collector_proof("darwin-arm64")
    proof[field] = value
    package = archives.package_identity(package_bytes(), "darwin-arm64", "2.12.2")
    with pytest.raises(ValueError):
        validate({"collector-parallel.json": policy.canonical(proof)}, package)


@pytest.mark.parametrize("field,value", [
    ("worker_pids", [100, 101]), ("worker_pids", [101, 101]),
    ("max_concurrency", 1), ("used_serial_fallback", True),
    ("infrastructure_error", "present"), ("file_error_count", 1), ("span_count", 8),
])
def test_collector_proof_cannot_disguise_serial_or_failed_work(field, value):
    proof = deepcopy(collector_proof("darwin-arm64"))
    proof["cold"]["usage_run"][field] = value
    package = archives.package_identity(package_bytes(), "darwin-arm64", "2.12.2")
    with pytest.raises(ValueError):
        validate({"collector-parallel.json": policy.canonical(proof)}, package)


def test_old_one_file_smoke_cannot_qualify_package():
    package = archives.package_identity(package_bytes(), "darwin-arm64", "2.12.2")
    with pytest.raises(ValueError, match="Missing collector"):
        validate({}, package)


@pytest.mark.parametrize("field,value", [
    ("completed_events", 0), ("completed_events", True), ("coverage_complete", False),
    ("pending_files", 1), ("pending_bytes", 1),
    ("source_bytes_read", 0), ("corpus_bytes", 100), ("oracle_equal", False),
])
def test_cold_work_cannot_be_completed_by_later_capture(field, value):
    proof = collector_proof("darwin-arm64")
    proof["cold"][field] = value
    package = archives.package_identity(package_bytes(), "darwin-arm64", "2.12.2")
    with pytest.raises(ValueError, match="cold capture"):
        validate({"collector-parallel.json": policy.canonical(proof)}, package)


def test_native_cleanup_observation_is_mandatory():
    proof = collector_proof("darwin-arm64")
    proof.pop("cleanup")
    package = archives.package_identity(package_bytes(), "darwin-arm64", "2.12.2")
    with pytest.raises(ValueError, match="timeout cleanup"):
        validate({"collector-parallel.json": policy.canonical(proof)}, package)
