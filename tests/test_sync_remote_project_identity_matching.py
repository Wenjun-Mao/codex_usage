from __future__ import annotations

from pathlib import Path

from _sync_remote_project_support import (
    PROJECT_A,
    PROJECT_B,
    materialize_direct,
    resolved_repository_identity,
)

from codex_usage.project_identity import normalize_project_key


def test_declared_repository_conflict_is_not_masked_by_matching_path_alias(
    tmp_path: Path,
) -> None:
    path_alias = normalize_project_key(str(tmp_path / "shared-checkout"))
    materialized = materialize_direct(
        tmp_path / "sync",
        indexed_project=PROJECT_A,
        aliases=(path_alias,),
        actual_project=PROJECT_B,
        actual_cwd=path_alias,
    )

    assert [issue.code for issue in materialized.issues] == [
        "remote_project_identity_mismatch"
    ]


def test_selected_remote_accepts_actual_path_only_identity_matching_index_alias(
    tmp_path: Path,
) -> None:
    actual_path_identity = normalize_project_key(str(tmp_path / "retired-checkout"))
    materialized = materialize_direct(
        tmp_path / "sync",
        indexed_project=PROJECT_A,
        aliases=(actual_path_identity,),
        actual_project="",
        actual_cwd=actual_path_identity,
    )

    assert not any(
        issue.code == "remote_project_identity_mismatch"
        for issue in materialized.issues
    )


def test_selected_remote_accepts_declared_repository_matching_index_repo_alias(
    tmp_path: Path,
) -> None:
    materialized = materialize_direct(
        tmp_path / "sync",
        indexed_project=PROJECT_A,
        aliases=(PROJECT_B,),
        actual_project=PROJECT_B,
        actual_cwd="/remote/project-b",
    )

    assert not any(
        issue.code == "remote_project_identity_mismatch"
        for issue in materialized.issues
    )


def test_selected_remote_accepts_declared_file_repository_matching_canonical_key(
    tmp_path: Path,
) -> None:
    repository = "file:///repos/example-project.git"
    identity = resolved_repository_identity(repository)
    assert identity.key == "file:///repos/example-project"
    materialized = materialize_direct(
        tmp_path / "sync",
        indexed_project=identity.key,
        aliases=(),
        actual_project=repository,
        actual_cwd="/remote/example-project",
    )

    assert not any(
        issue.code == "remote_project_identity_mismatch"
        for issue in materialized.issues
    )


def test_selected_remote_accepts_declared_local_repository_matching_canonical_key(
    tmp_path: Path,
) -> None:
    repository = str(tmp_path / "example-project.git")
    identity = resolved_repository_identity(repository)
    assert identity.key == normalize_project_key(str(tmp_path / "example-project"))
    materialized = materialize_direct(
        tmp_path / "sync",
        indexed_project=identity.key,
        aliases=(),
        actual_project=repository,
        actual_cwd="/remote/example-project",
    )

    assert not any(
        issue.code == "remote_project_identity_mismatch"
        for issue in materialized.issues
    )


def test_selected_remote_accepts_declared_custom_repository_matching_canonical_key(
    tmp_path: Path,
) -> None:
    repository = "custom:example-project.git"
    identity = resolved_repository_identity(repository)
    assert identity.key == "custom:example-project"
    materialized = materialize_direct(
        tmp_path / "sync",
        indexed_project=identity.key,
        aliases=(),
        actual_project=repository,
        actual_cwd="/remote/example-project",
    )

    assert not any(
        issue.code == "remote_project_identity_mismatch"
        for issue in materialized.issues
    )
