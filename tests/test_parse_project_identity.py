from dataclasses import replace
import json
import shutil
from unittest.mock import patch

import pytest

from codex_usage.models import SessionMetadata
from codex_usage.project_identity import resolve_project_identity
from codex_usage.session_project_identity import ParseProjectIdentity


def metadata(tmp_path, **kwargs):
    return SessionMetadata(session_id="task", file_path=tmp_path / "source.jsonl", **kwargs)


def origin(path, url="https://example.invalid/one.git"):
    (path / ".git").mkdir(parents=True, exist_ok=True)
    (path / ".git/config").write_text(f'[remote "origin"]\nurl = {url}\n')


def test_identity_resolution_scales_with_scopes_not_responses(tmp_path):
    origin(tmp_path / "repo")
    source = metadata(tmp_path, cwd=str(tmp_path / "repo"))
    with patch("codex_usage.session_project_identity.resolve_project_identity",
               wraps=resolve_project_identity) as resolver:
        scope = ParseProjectIdentity()
        for _ in range(1000):
            assert scope.resolve(source) == scope.resolve(source)
        assert resolver.call_count == 1
        scope.validate()
        assert resolver.call_count == 2
        another = ParseProjectIdentity()
        another.resolve(source)
        another.validate()
        assert resolver.call_count == 4


def test_empty_chunk_does_no_identity_work():
    with patch("codex_usage.session_project_identity.resolve_project_identity") as resolver:
        ParseProjectIdentity().validate()
    resolver.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("cwd", "/different"), ("git_repository_url", "https://example.invalid/two"),
    ("git_commit_hash", "a" * 40), ("session_id", "different"),
])
def test_raw_effective_identity_inputs_invalidate_scope(tmp_path, field, value):
    first = metadata(tmp_path)
    second = replace(first, **{field: value})
    with patch("codex_usage.session_project_identity.resolve_project_identity",
               wraps=resolve_project_identity) as resolver:
        scope = ParseProjectIdentity()
        scope.resolve(first)
        scope.resolve(second)
        scope.resolve(first)
        scope.validate()
        assert resolver.call_count == 5


def test_unrelated_metadata_does_not_retain_stale_record_fields(tmp_path):
    from codex_usage.session_usage_record import usage_record
    from codex_usage.models import TokenUsage
    first = metadata(tmp_path, git_branch="one")
    second = replace(first, git_branch="two", parent_thread_id="parent")
    scope = ParseProjectIdentity()
    identity = scope.resolve(first)
    assert scope.resolve(second) is identity
    result = usage_record(second.file_path, second, None, TokenUsage(), identity=identity,
                          model="model", turn_id="turn", effort="high", mode="plan")
    assert (result.git_branch, result.parent_thread_id, result.model, result.turn_id,
            result.effort, result.collaboration_mode) == ("two", "parent", "model", "turn", "high", "plan")


@pytest.mark.parametrize("mutation", ["origin", "disappear", "appear", "gitdir", "commondir"])
def test_fresh_validation_rejects_changed_checkout(tmp_path, mutation):
    repo = tmp_path / "repo"
    if mutation == "commondir":
        origin(repo)
        (repo / ".git/commondir").write_text(str(repo / ".git"))
    elif mutation != "appear":
        origin(repo)
    scope = ParseProjectIdentity()
    scope.resolve(metadata(tmp_path, cwd=str(repo)))
    if mutation == "origin":
        origin(repo, "https://example.invalid/two.git")
    elif mutation == "disappear":
        shutil.rmtree(repo)
    elif mutation == "appear":
        origin(repo)
    elif mutation == "gitdir":
        origin(tmp_path / "replacement", "https://example.invalid/two.git")
        shutil.rmtree(repo / ".git")
        (repo / ".git").write_text(f"gitdir: {tmp_path / 'replacement/.git'}\n")
    else:
        origin(tmp_path / "replacement", "https://example.invalid/two.git")
        (repo / ".git/config").unlink()
        (repo / ".git/commondir").write_text(str(tmp_path / "replacement/.git"))
    with pytest.raises(OSError, match="project identity changed"):
        scope.validate()


def test_earlier_nonfinal_scope_is_also_validated(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    origin(first)
    origin(second)
    scope = ParseProjectIdentity()
    scope.resolve(metadata(tmp_path, cwd=str(first)))
    scope.resolve(metadata(tmp_path, cwd=str(second)))
    origin(first, "https://example.invalid/changed.git")
    with pytest.raises(OSError, match="project identity changed"):
        scope.validate()


def test_git_errors_cannot_reuse_replacement(tmp_path, monkeypatch):
    from test_project_continuity import _checkout_with_replacement_origin
    repo, commit = _checkout_with_replacement_origin(tmp_path / "repo")
    source = metadata(tmp_path, cwd=str(repo), git_repository_url="https://example.invalid/old.git",
                      git_commit_hash=commit)
    scope = ParseProjectIdentity()
    assert scope.resolve(source).uses_current_checkout_origin
    monkeypatch.setattr("codex_usage.project_identity.subprocess.run",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("Git unavailable")))
    with pytest.raises(OSError, match="project identity changed"):
        scope.validate()
    assert ParseProjectIdentity().resolve(source).key == "https://example.invalid/old"


def test_head_ancestry_change_rejects_cached_replacement(tmp_path):
    from test_project_continuity import _checkout_with_replacement_origin, _git
    repo, commit = _checkout_with_replacement_origin(tmp_path / "repo")
    source = metadata(tmp_path, cwd=str(repo), git_repository_url="https://example.invalid/old.git",
                      git_commit_hash=commit)
    scope = ParseProjectIdentity()
    assert scope.resolve(source).uses_current_checkout_origin
    _git(repo, "checkout", "--orphan", "unrelated")
    _git(repo, "commit", "--allow-empty", "-m", "unrelated root")
    with pytest.raises(OSError, match="project identity changed"):
        scope.validate()


def test_linked_worktree_freshly_checks_shared_origin(tmp_path):
    from test_project_continuity import _checkout_with_replacement_origin, _git
    primary, commit = _checkout_with_replacement_origin(tmp_path / "primary")
    linked = tmp_path / "linked"
    _git(primary, "worktree", "add", "-b", "linked", str(linked))
    scope = ParseProjectIdentity()
    source = metadata(tmp_path, cwd=str(linked), git_repository_url="https://example.invalid/old.git",
                      git_commit_hash=commit)
    assert scope.resolve(source).uses_current_checkout_origin
    _git(primary, "remote", "set-url", "origin", "https://example.invalid/changed.git")
    with pytest.raises(OSError, match="project identity changed"):
        scope.validate()


def test_benign_git_config_change_keeps_same_identity(tmp_path):
    repo = tmp_path / "repo"
    origin(repo)
    scope = ParseProjectIdentity()
    scope.resolve(metadata(tmp_path, cwd=str(repo)))
    with (repo / ".git/config").open("a") as stream:
        stream.write("\n[core]\nfilemode = false\n")
    scope.validate()


def test_return_to_prior_scope_cannot_hide_identity_change(tmp_path):
    repo = tmp_path / "repo"
    origin(repo)
    scope = ParseProjectIdentity()
    first = metadata(tmp_path, cwd=str(repo))
    scope.resolve(first)
    scope.resolve(replace(first, session_id="other"))
    origin(repo, "https://example.invalid/changed.git")
    with pytest.raises(OSError, match="project identity changed"):
        scope.resolve(first)


def test_parser_reuses_identity_without_changing_checkpoint_or_records(tmp_path):
    from codex_usage.parser import parse_session_generation
    from parser_test_support import session_meta, token, usage, write_session
    repo = tmp_path / "repo"
    origin(repo)
    path = write_session(tmp_path / "sessions", [session_meta(cwd=str(repo))] + [
        token(f"2026-10-16T12:00:{i:02}Z", usage(total=100*(i+1))) for i in range(50)])
    with patch("codex_usage.session_project_identity.resolve_project_identity",
               wraps=resolve_project_identity) as resolver:
        result = parse_session_generation(path)
    assert len(result.records) == 50
    assert resolver.call_count == 2
    from codex_usage.session_parser_models import parser_state_to_json
    assert "identity" not in json.loads(parser_state_to_json(result.checkpoint.state))


def test_identity_race_exhausts_bounded_retry_and_retains_old_checkpoint(tmp_path, monkeypatch):
    from codex_usage.agent_paths import ledger_database_path
    from codex_usage.ledger_schema import open_ledger
    from codex_usage.session_cache import refresh_cached_session_data
    from parser_test_support import session_meta, token, usage, write_session
    repo = tmp_path / "repo"
    origin(repo)
    sessions = tmp_path / "sessions"
    path = write_session(sessions, [session_meta(cwd=str(repo)),
        token("2026-10-16T12:00:00Z", usage(total=100))])
    db = ledger_database_path(tmp_path)
    with open_ledger(db):
        pass
    kwargs = dict(cache_database_path=db, max_workers=1, auto_transitions=False,
                  refresh_storage_metadata=False)
    refresh_cached_session_data([sessions], **kwargs)
    with open_ledger(db, read_only=True) as connection:
        before = tuple(connection.execute("select byte_offset,state_json from parser_checkpoints").fetchone())
    with path.open("a") as stream:
        stream.write("\n"+json.dumps(token("2026-10-16T12:01:00Z", usage(total=200)))+"\n")
    calls = 0

    def racing(source):
        nonlocal calls
        result = resolve_project_identity(source)
        calls += 1
        if calls % 2:
            origin(repo, f"https://example.invalid/change-{calls}.git")
        return result

    monkeypatch.setattr("codex_usage.session_project_identity.resolve_project_identity", racing)
    result = refresh_cached_session_data([sessions], **kwargs)
    assert result.stats.file_errors == 1
    assert calls == 6
    with open_ledger(db, read_only=True) as connection:
        assert tuple(connection.execute("select byte_offset,state_json from parser_checkpoints").fetchone()) == before
        assert connection.execute("select count(*) from usage_records").fetchone()[0] == 1
