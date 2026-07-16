from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCS = (ROOT / "README.md", ROOT / "extensions/vscode/README.md")
CHANGELOGS = (ROOT / "CHANGELOG.md", ROOT / "extensions/vscode/CHANGELOG.md")


def test_current_docs_lead_with_deliberate_task_transfer() -> None:
    for path in CURRENT_DOCS:
        text = path.read_text(encoding="utf-8")
        assert "Task Transfer" in text
        assert "Export Tasks" in text
        assert "Import Tasks" in text
        assert "Review Transfer Status" in text
        assert "built-in handoff" in text.casefold()
        assert "desktop app is not required" in text.casefold()
        assert "reload vs code or restart the codex app" in text.casefold()
        assert "token" in text.casefold() and "without task transfer" in text.casefold()


def test_current_docs_do_not_claim_ongoing_sync_or_persisted_selection() -> None:
    forbidden = (
        "Setup required",
        "Pause Sync",
        "Resume Sync",
        "Change Tasks",
        "Clear Sync Setup",
        "Pull Tasks",
        "Push Tasks",
        "selected task ids",
    )
    for path in CURRENT_DOCS:
        text = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase.casefold() not in text.casefold(), (path, phrase)


def test_every_changelog_has_unreleased_and_dated_release_headings() -> None:
    heading = re.compile(r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})(?: - .+)?$", re.MULTILINE)
    for path in CHANGELOGS:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# Changelog\n\n## Unreleased\n")
        release_lines = [line for line in text.splitlines() if line.startswith("## 0.")]
        assert release_lines
        assert all(heading.fullmatch(line) for line in release_lines)


def test_matching_changelog_versions_have_identical_dates() -> None:
    def dates(path: Path) -> dict[str, str]:
        return dict(re.findall(r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})", path.read_text(), re.MULTILINE))

    root_dates = dates(CHANGELOGS[0])
    extension_dates = dates(CHANGELOGS[1])
    assert {version: root_dates[version] for version in extension_dates} == extension_dates
