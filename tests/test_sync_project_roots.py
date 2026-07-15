from __future__ import annotations

import json

from codex_usage.sync.project_roots import discover_project_roots


def test_discover_project_roots_preserves_codex_saved_path_spelling(tmp_path):
    actual_project = tmp_path / "actual-project"
    actual_project.mkdir()
    git_dir = actual_project / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/example/project.git\n',
        encoding="utf-8",
    )
    saved_project = tmp_path / "saved-project"
    saved_project.symlink_to(actual_project, target_is_directory=True)

    codex_home = tmp_path / "codex-home"
    sessions_dir = codex_home / "sessions"
    sessions_dir.mkdir(parents=True)
    (codex_home / ".codex-global-state.json").write_text(
        json.dumps({"electron-saved-workspace-roots": [str(saved_project)]}),
        encoding="utf-8",
    )

    roots = discover_project_roots((sessions_dir,))

    assert roots == {
        "https://github.com/example/project": (saved_project,),
    }
