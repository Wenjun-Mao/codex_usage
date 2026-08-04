from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README_PATHS = (ROOT / "README.md", ROOT / "extensions/vscode/README.md")
CHANGELOG_PATHS = (ROOT / "CHANGELOG.md", ROOT / "extensions/vscode/CHANGELOG.md")
RELEASE_CHECKLIST = ROOT / "docs/release.md"


def markdown_section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, (path, heading)
    return match.group("body")


def normalized_prose(value: str) -> str:
    return " ".join(value.casefold().split())


def test_readmes_lead_with_project_role_model_reporting() -> None:
    headings = {
        README_PATHS[0]: "## What The Dashboard Shows",
        README_PATHS[1]: "## Features",
    }

    for path, heading in headings.items():
        text = path.read_text(encoding="utf-8")
        reporting = normalized_prose(markdown_section(path, heading))
        task_transfer_position = text.index("## Task Transfer")
        reporting_position = text.index(heading)

        assert task_transfer_position > reporting_position + len(
            markdown_section(path, heading)
        )
        for phrase in (
            "root tasks",
            "subagents",
            "model",
            "project",
            "codex credits",
            "api-equivalent",
            "task transfer",
        ):
            assert phrase in reporting, (path, phrase)


def test_release_checklist_locks_marketplace_screenshot_gate() -> None:
    checklist = normalized_prose(RELEASE_CHECKLIST.read_text(encoding="utf-8"))

    for phrase in (
        "uv run playwright install chromium",
        "uv run python scripts/generate_marketplace_screenshot.py",
        "uv run python scripts/generate_marketplace_screenshot.py --check",
        "1440 x 900",
        "visually review",
    ):
        assert phrase in checklist, phrase


def test_unreleased_changelogs_describe_role_model_breakdown() -> None:
    required_phrases = (
        "root-task",
        "structured-subagent",
        "shared model mix colors",
        "visual-only other",
        "schema 5",
        "once",
    )

    for path in CHANGELOG_PATHS:
        unreleased = normalized_prose(markdown_section(path, "## Unreleased"))
        for phrase in required_phrases:
            assert phrase in unreleased, (path, phrase)


def test_historical_1_1_0_changelogs_keep_schema_4_wording() -> None:
    heading = "## 1.1.0 - 2026-08-03 - Incremental Usage Cache"

    for path in CHANGELOG_PATHS:
        release = normalized_prose(markdown_section(path, heading))
        assert "schema 4" in release
