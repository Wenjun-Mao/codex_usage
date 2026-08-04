from __future__ import annotations

import json
from pathlib import Path

from parser_test_support import (
    session_meta,
    token,
    turn_context,
    usage,
    write_session,
)

from codex_usage.aggregation import (
    aggregate_records,
    filter_records_by_project_keys,
    resolve_timezone,
    summarize_records,
)
from codex_usage.models import SUBAGENT_USAGE_ROLE
from codex_usage.parser import (
    finalize_session_records,
    parse_session_file,
    parse_session_files,
)


def test_project_grouping_falls_back_to_cwd_when_git_missing(tmp_path: Path) -> None:
    path = write_session(
        tmp_path,
        [
            session_meta(cwd="D:\\Projects\\Demo"),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=100)),
        ],
    )

    record = parse_session_file(path)[0]

    assert record.project_key == "d:/projects/demo"
    assert record.project_label == "Demo"


def test_project_grouping_resolves_missing_git_url_from_cwd_git_config(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "Persona_Generators"
    nested = repo / "src" / "feature"
    git_dir = repo / ".git"
    nested.mkdir(parents=True)
    git_dir.mkdir()
    (git_dir / "config").write_text(
        "[core]\n"
        "\trepositoryformatversion = 0\n"
        '[remote "origin"]\n'
        "\turl = https://github.com/Wenjun-Mao/persona_generators.git",
        encoding="utf-8",
    )
    path = write_session(
        tmp_path / "session",
        [
            session_meta(cwd=str(nested)),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=100)),
        ],
    )

    record = parse_session_file(path)[0]

    assert record.project_key == "https://github.com/wenjun-mao/persona_generators"
    assert record.project_label == "persona_generators"
    assert _normalized_path(str(nested)) in record.project_aliases


def test_project_grouping_does_not_escape_external_project_boundary(
    tmp_path: Path,
) -> None:
    enclosing_repo = tmp_path / "ContentShuttle"
    external_project = enclosing_repo / "zz_external_projects" / "signoz-stack"
    external_project.mkdir(parents=True)
    git_dir = enclosing_repo / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/example/contentshuttle.git\n',
        encoding="utf-8",
    )
    path = write_session(
        tmp_path / "session",
        [
            session_meta(cwd=str(external_project)),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=100)),
        ],
    )

    record = parse_session_file(path)[0]

    assert record.project_key == _normalized_path(str(external_project))
    assert record.project_label == "signoz-stack"


def test_parse_session_files_uses_parent_project_for_subagent_without_git_metadata(
    tmp_path: Path,
) -> None:
    enclosing_repo = tmp_path / "ContentShuttle"
    child_cwd = enclosing_repo / "zz_external_projects" / "signoz-stack"
    child_cwd.mkdir(parents=True)
    git_dir = enclosing_repo / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/example/contentshuttle.git\n',
        encoding="utf-8",
    )
    parent = write_session(
        tmp_path / "parent",
        [
            session_meta(
                cwd=str(child_cwd),
                repo="https://github.com/example/signoz-stack.git",
                session_id="parent-thread",
            ),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=100)),
        ],
    )
    child = write_session(
        tmp_path / "child",
        [
            session_meta(
                cwd=str(child_cwd),
                session_id="child-thread",
                parent_thread_id="parent-thread",
            ),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=75)),
        ],
    )

    rows = aggregate_records(
        parse_session_files([parent, child]), "project", resolve_timezone("UTC")
    )

    assert [(row.key, row.usage.total_tokens) for row in rows] == [
        ("https://github.com/example/signoz-stack", 175)
    ]


def test_finalize_session_records_preserves_parent_identity_inheritance(
    tmp_path: Path,
) -> None:
    parent = write_session(
        tmp_path / "parent",
        [
            session_meta(
                cwd="/repo/parent",
                repo="https://github.com/example/parent.git",
                session_id="parent-thread",
            ),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=100)),
        ],
    )
    child = write_session(
        tmp_path / "child",
        [
            session_meta(
                cwd="/repo/child-without-git",
                session_id="child-thread",
                parent_thread_id="parent-thread",
            ),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=50)),
        ],
    )

    finalized = finalize_session_records(
        [parse_session_file(parent), parse_session_file(child)]
    )

    child_record = next(
        record for record in finalized if record.session_id == "child-thread"
    )
    assert child_record.project_key == "https://github.com/example/parent"
    assert child_record.project_label == "parent"
    assert child_record.git_repository_url == "https://github.com/example/parent.git"
    assert "/repo/child-without-git" in child_record.project_aliases
    assert child_record.usage_role == SUBAGENT_USAGE_ROLE


def test_project_grouping_prefers_json_git_url_over_cwd_git_config(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "demo"
    git_dir = repo / ".git"
    repo.mkdir()
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/example/from-cwd.git\n',
        encoding="utf-8",
    )
    path = write_session(
        tmp_path / "session",
        [
            session_meta(
                cwd=str(repo), repo="https://github.com/example/from-json.git"
            ),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=100)),
        ],
    )

    record = parse_session_file(path)[0]

    assert record.project_key == "https://github.com/example/from-json"
    assert _normalized_path(str(repo)) in record.project_aliases


def test_project_alias_env_no_longer_rewrites_project_identity(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(
        "CODEX_USAGE_PROJECT_ALIASES",
        json.dumps(
            {
                "https://github.com/example/signoz-stack.git":
                    "https://github.com/example/ops-board.git"
            }
        ),
    )
    path = write_session(
        tmp_path / "session",
        [
            session_meta(
                cwd="D:\\Projects\\signoz-stack",
                repo="https://github.com/example/signoz-stack.git",
            ),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=100)),
        ],
    )

    record = parse_session_file(path)[0]

    assert record.project_key == "https://github.com/example/signoz-stack"
    assert "https://github.com/example/ops-board" not in record.project_aliases
    assert "d:/projects/signoz-stack" in record.project_aliases


def test_project_grouping_normalizes_ssh_git_remotes(tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    git_dir = repo / ".git"
    repo.mkdir()
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:Wenjun-Mao/persona_generators.git\n',
        encoding="utf-8",
    )
    path = write_session(
        tmp_path / "session",
        [
            session_meta(cwd=str(repo)),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=100)),
        ],
    )

    record = parse_session_file(path)[0]

    assert record.project_key == "https://github.com/wenjun-mao/persona_generators"


def test_project_aggregation_combines_json_git_url_and_cwd_resolved_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "persona_generators"
    git_dir = repo / ".git"
    repo.mkdir()
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:Wenjun-Mao/persona_generators.git\n',
        encoding="utf-8",
    )
    first = write_session(
        tmp_path / "first",
        [
            session_meta(
                cwd=str(repo),
                repo="https://github.com/Wenjun-Mao/persona_generators.git",
                session_id="session-1",
            ),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=100)),
        ],
    )
    second = write_session(
        tmp_path / "second",
        [
            session_meta(cwd=str(repo), session_id="session-2"),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=75)),
        ],
    )
    records = parse_session_file(first) + parse_session_file(second)

    rows = aggregate_records(records, "project", resolve_timezone("UTC"))

    assert [(row.key, row.usage.total_tokens) for row in rows] == [
        ("https://github.com/wenjun-mao/persona_generators", 175)
    ]
    assert summarize_records(
        filter_records_by_project_keys(
            records, ["https://github.com/wenjun-mao/persona_generators"]
        )
    ).usage.total_tokens == 175
    assert summarize_records(
        filter_records_by_project_keys(records, [_normalized_path(str(repo))])
    ).usage.total_tokens == 175


def test_project_filter_supports_empty_single_multiple_and_unmatched_keys(
    tmp_path: Path,
) -> None:
    first = write_session(
        tmp_path / "first",
        [
            session_meta(cwd="/repo/first"),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=100)),
        ],
    )
    second = write_session(
        tmp_path / "second",
        [
            session_meta(cwd="/repo/second"),
            turn_context(model="gpt-5.5"),
            token("2026-04-29T10:00:00Z", usage(total=75)),
        ],
    )
    records = parse_session_file(first) + parse_session_file(second)

    assert summarize_records(
        filter_records_by_project_keys(records, [])
    ).usage.total_tokens == 175
    assert summarize_records(
        filter_records_by_project_keys(records, ["/repo/first"])
    ).usage.total_tokens == 100
    assert summarize_records(
        filter_records_by_project_keys(records, ["/repo/first", "/repo/second"])
    ).usage.total_tokens == 175
    assert filter_records_by_project_keys(records, ["/repo/missing"]) == []


def _normalized_path(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").casefold()
