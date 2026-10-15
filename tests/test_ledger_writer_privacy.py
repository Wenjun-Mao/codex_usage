"""Refused ledger paths and error cleanup never chmod an alias target."""
from pathlib import Path

import pytest

import codex_usage.ledger_schema as schema
from codex_usage.ledger_writer_contract import LedgerCompatibilityError


def alias(target, link, monkeypatch):
    try:
        link.symlink_to(target)
    except OSError:
        # Admission still has a deterministic unit probe on hosts without symlink privileges.
        link.hardlink_to(target)
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == link or original(path))


@pytest.mark.parametrize("kind", ["database", "wal", "shm", "journal"])
def test_refused_alias_is_detected_before_any_privacy_mutation(tmp_path, monkeypatch, kind):
    ledger = tmp_path / "ledger.sqlite3"
    with schema.open_ledger(ledger):
        pass
    target = ledger if kind == "database" else tmp_path / "unrelated-sentinel"
    if kind != "database":
        target.write_bytes(b"unrelated sentinel")
    target.chmod(0o640)
    requested = tmp_path / "alias.sqlite3" if kind == "database" else ledger
    link = requested if kind == "database" else ledger.with_name(ledger.name+"-"+kind)
    alias(target, link, monkeypatch)
    before = target.stat().st_mode
    with pytest.raises(LedgerCompatibilityError, match="nonsymlink"):
        with schema.open_ledger(requested):
            pass
    assert target.stat().st_mode == before


def test_cleanup_does_not_follow_a_sidecar_alias_created_after_admission(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.sqlite3"
    with schema.open_ledger(ledger):
        pass
    target = tmp_path / "sentinel"
    target.write_bytes(b"unrelated")
    target.chmod(0o640)
    mode = target.stat().st_mode

    def fail_after_alias(*_args, **_kwargs):
        alias(target, ledger.with_name(ledger.name+"-wal"), monkeypatch)
        raise RuntimeError("synthetic refused open")

    monkeypatch.setattr(schema, "ensure_ledger_schema", fail_after_alias)
    with pytest.raises(RuntimeError, match="synthetic refused open"):
        with schema.open_ledger(ledger):
            pass
    assert target.stat().st_mode == mode


@pytest.mark.parametrize("setup_failed", [False, True])
def test_cleanup_diagnostics_preserve_primary_refusal_but_surface_after_success(tmp_path, monkeypatch, setup_failed):
    ledger = tmp_path / "ledger.sqlite3"
    with schema.open_ledger(ledger):
        pass

    def refused(*_args, **_kwargs):
        raise LedgerCompatibilityError("synthetic primary refusal")

    def cleanup_failure(*_args):
        raise PermissionError("synthetic cleanup permission denial")

    if setup_failed:
        monkeypatch.setattr(schema, "ensure_ledger_schema", refused)
    monkeypatch.setattr(schema, "ensure_private_sqlite_files", cleanup_failure)
    error = LedgerCompatibilityError if setup_failed else PermissionError
    with pytest.raises(error) as raised:
        with schema.open_ledger(ledger):
            pass
    if setup_failed:
        assert str(raised.value) == "synthetic primary refusal"
        assert any("PermissionError" in note and "cleanup permission denial" in note for note in raised.value.__notes__)
    else:
        assert "cleanup permission denial" in str(raised.value)


def test_successful_context_does_not_treat_an_outer_handled_exception_as_its_failure(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.sqlite3"
    with schema.open_ledger(ledger):
        pass

    def cleanup_failure(*_args):
        raise PermissionError("synthetic cleanup failure inside outer handler")

    monkeypatch.setattr(schema, "ensure_private_sqlite_files", cleanup_failure)
    try:
        raise ValueError("unrelated outer error")
    except ValueError as outer:
        with pytest.raises(PermissionError, match="inside outer handler"):
            with schema.open_ledger(ledger):
                pass
        assert not getattr(outer, "__notes__", [])
