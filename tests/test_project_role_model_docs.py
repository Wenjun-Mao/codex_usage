from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README_PATHS = (ROOT / "README.md", ROOT / "extensions/vscode/README.md")
CHANGELOG_PATHS = (ROOT / "CHANGELOG.md", ROOT / "extensions/vscode/CHANGELOG.md")
RELEASE_CHECKLIST = ROOT / "docs/release.md"
SCREENSHOT_PATH = ROOT / "docs/marketplace/dashboard-synthetic.png"
SCREENSHOT_MARKDOWN = "![Synthetic Codex Usage Dashboard screenshot]"

README_REPORTING_SECTIONS = {
    README_PATHS[0]: {
        "heading": "## What The Dashboard Shows",
        "package_heading": "## VS Code Packages",
        "final_feature_line": "- Optional Task Transfer moves selected active tasks between computers; token reporting works without it.",
    },
    README_PATHS[1]: {
        "heading": "## Features",
        "package_heading": "## Install",
        "final_feature_line": "- Detects high-confidence project transitions and can split dashboard usage after verified local repository changes.",
    },
}

SCHEMA_4_RELEASE_BULLET = (
    "- Rebuilt the disposable schema 4 cache once after upgrade, then refreshed "
    "only changed complete files in one pass for usage and transition candidates."
)


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
    for path, details in README_REPORTING_SECTIONS.items():
        text = path.read_text(encoding="utf-8")
        heading = details["heading"]
        reporting = normalized_prose(markdown_section(path, heading))
        task_transfer_position = text.index("## Task Transfer")
        reporting_position = text.index(heading)
        reporting_start = reporting_position + len(heading)
        ordering = {
            phrase: reporting.index(phrase.casefold())
            for phrase in (
                "project breakdown separates each project into user-visible root tasks and structured subagents",
                "model mix uses shared model colors",
                "total tokens",
                "api-equivalent",
                "codex credits",
                "task transfer",
            )
        }

        assert "local-first" in text[:reporting_position].casefold()
        assert task_transfer_position > reporting_start + len(
            markdown_section(path, heading)
        )
        assert ordering["project breakdown separates each project into user-visible root tasks and structured subagents"] < ordering[
            "model mix uses shared model colors"
        ]
        assert ordering["model mix uses shared model colors"] < ordering["total tokens"]
        assert ordering["total tokens"] < ordering["api-equivalent"]
        assert ordering["api-equivalent"] < ordering["codex credits"]
        assert ordering["codex credits"] < ordering["task transfer"]


def test_readmes_place_tracked_screenshot_after_opening_features() -> None:
    assert SCREENSHOT_PATH.is_file()

    for path, details in README_REPORTING_SECTIONS.items():
        text = path.read_text(encoding="utf-8")
        screenshot_position = text.index(SCREENSHOT_MARKDOWN)
        reporting_position = text.index(details["heading"])
        package_position = text.index(details["package_heading"])
        task_transfer_position = text.index("## Task Transfer")
        preceding_line = text[:screenshot_position].rstrip().splitlines()[-1]

        assert reporting_position < screenshot_position
        assert screenshot_position < package_position
        assert screenshot_position < task_transfer_position
        assert preceding_line == details["final_feature_line"]


def test_release_checklist_locks_marketplace_screenshot_gate() -> None:
    checklist = RELEASE_CHECKLIST.read_text(encoding="utf-8")

    for phrase in (
        "uv run playwright install chromium",
        "1440 x 900",
        "visually review",
    ):
        assert phrase.casefold() in checklist.casefold(), phrase

    for command in (
        "uv run python scripts/generate_marketplace_screenshot.py",
        "uv run python scripts/generate_marketplace_screenshot.py --check",
    ):
        assert re.search(rf"(?m)^{re.escape(command)}$", checklist), command


def test_1_2_0_changelogs_describe_role_model_breakdown() -> None:
    required_phrases = (
        "root-task",
        "structured-subagent",
        "shared model mix colors",
        "visual-only other",
        "schema 5",
        "once",
    )
    heading = "## 1.2.0 - 2026-08-04 - Project Role And Model Insights"

    for path in CHANGELOG_PATHS:
        text = path.read_text(encoding="utf-8")
        assert text.count("## Unreleased") == 1
        assert text.count(heading) == 1
        release = normalized_prose(markdown_section(path, heading))
        for phrase in required_phrases:
            assert phrase in release, (path, phrase)


def test_historical_1_1_0_changelogs_keep_schema_4_wording() -> None:
    heading = "## 1.1.0 - 2026-08-03 - Incremental Usage Cache"

    for path in CHANGELOG_PATHS:
        text = path.read_text(encoding="utf-8")
        assert text.count(heading) == 1
        release = markdown_section(path, heading)
        assert SCHEMA_4_RELEASE_BULLET in release
