"""Replica proof I/O remains bounded and accounts for failed reads."""
from dataclasses import replace

import pytest

from codex_usage.session_inventory import collect_session_file_inventory
from codex_usage.session_replica_guards import (
    ReplicaEvidenceError, ReplicaReadBudget, capture_prefix, prove_prefixes,
)


def entry(tmp_path):
    path = tmp_path / "sample.jsonl"
    path.write_bytes(b"a"*128)
    return collect_session_file_inventory([tmp_path], read_metadata=False)[0]


def test_prefix_proofs_deduplicate_reads_and_reserve_before_open(tmp_path):
    source = entry(tmp_path)
    budget = ReplicaReadBudget(512)
    prefix = capture_prefix(source, budget)
    assert budget.bytes_read == 256
    prove_prefixes(source, (prefix, prefix), budget)
    assert budget.bytes_read == 512 and budget.remaining == 0
    with pytest.raises(ReplicaEvidenceError, match="read_budget"):
        capture_prefix(source, budget)
    assert budget.bytes_read == 512


def test_changed_inventory_is_rejected_before_reading(tmp_path):
    source = entry(tmp_path)
    budget = ReplicaReadBudget(1024)
    with pytest.raises(ReplicaEvidenceError, match="source_changed"):
        capture_prefix(replace(source, source_inode=source.source_inode+1), budget)
    assert budget.bytes_read == 0


def test_failed_digest_still_charges_bytes_already_read(tmp_path, monkeypatch):
    source = entry(tmp_path)
    budget = ReplicaReadBudget(1024)

    def failed(reader, start, _end):
        reader.seek(start)
        reader.read(3)
        raise OSError("synthetic short read")

    monkeypatch.setattr("codex_usage.session_replica_guards.digest_range", failed)
    with pytest.raises(ReplicaEvidenceError, match="source_unavailable"):
        capture_prefix(source, budget)
    assert budget.bytes_read == 3


def test_source_change_during_proof_is_not_a_valid_relationship(tmp_path, monkeypatch):
    from codex_usage import session_replica_guards as guards

    source = entry(tmp_path)
    original = guards.digest_range

    def mutate(reader, start, end):
        result = original(reader, start, end)
        if start == 0:
            with source.path.open("ab") as handle:
                handle.write(b"x")
        return result

    monkeypatch.setattr(guards, "digest_range", mutate)
    budget = ReplicaReadBudget(1024)
    with pytest.raises(ReplicaEvidenceError, match="source_changed"):
        capture_prefix(source, budget)
    assert budget.bytes_read == 256
