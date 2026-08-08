from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHANGELOGS = (ROOT / "CHANGELOG.md", ROOT / "extensions/vscode/CHANGELOG.md")
SUPPORT_DOCS = (ROOT / "SUPPORT.md", ROOT / "extensions/vscode/SUPPORT.md")

ROOT_RELEASE_DATES = {
    "1.5.0": "2026-08-07",
    "1.4.0": "2026-08-07",
    "1.3.0": "2026-08-07",
    "1.2.0": "2026-08-04",
    "1.1.0": "2026-08-03",
    "1.0.0": "2026-08-03",
    "0.1.42": "2026-07-31",
    "0.1.41": "2026-07-30",
    "0.1.40": "2026-07-29",
    "0.1.39": "2026-07-29",
    "0.1.38": "2026-07-23",
    "0.1.37": "2026-07-21",
    "0.1.36": "2026-07-16",
    "0.1.35": "2026-07-14",
    "0.1.34": "2026-07-14",
    "0.1.33": "2026-07-14",
    "0.1.32": "2026-07-09",
    "0.1.31": "2026-07-03",
    "0.1.30": "2026-06-24",
    "0.1.29": "2026-06-15",
    "0.1.28": "2026-06-12",
    "0.1.27": "2026-06-11",
    "0.1.26": "2026-06-11",
    "0.1.25": "2026-06-11",
    "0.1.24": "2026-05-30",
    "0.1.23": "2026-05-30",
    "0.1.22": "2026-05-30",
    "0.1.21": "2026-05-30",
    "0.1.20": "2026-05-30",
    "0.1.19": "2026-05-27",
    "0.1.18": "2026-05-25",
    "0.1.17": "2026-05-25",
    "0.1.16": "2026-05-25",
    "0.1.15": "2026-05-25",
    "0.1.14": "2026-05-25",
    "0.1.13": "2026-05-25",
    "0.1.12": "2026-05-25",
    "0.1.11": "2026-05-24",
    "0.1.10": "2026-05-24",
    "0.1.9": "2026-05-24",
    "0.1.8": "2026-05-24",
    "0.1.6": "2026-05-24",
    "0.1.5": "2026-05-21",
    "0.1.4": "2026-05-21",
    "0.1.3": "2026-05-19",
    "0.1.0": "2026-05-19",
}
EXTENSION_RELEASE_VERSIONS = (
    "1.5.0",
    "1.4.0",
    "1.3.0",
    "1.2.0",
    "1.1.0",
    "1.0.0",
    "0.1.42",
    "0.1.41",
    "0.1.40",
    "0.1.39",
    "0.1.38",
    "0.1.37",
    "0.1.36",
    "0.1.35",
    "0.1.34",
    "0.1.33",
    "0.1.32",
    "0.1.31",
    "0.1.30",
    "0.1.29",
    "0.1.28",
    "0.1.27",
    "0.1.26",
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


def release_dates(path: Path) -> dict[str, str]:
    return dict(
        re.findall(
            r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})(?: - .+)?$",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )


def test_every_changelog_has_unreleased_and_dated_release_headings() -> None:
    heading = re.compile(
        r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})(?: - .+)?$",
        re.MULTILINE,
    )
    for path in CHANGELOGS:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# Changelog\n\n## Unreleased\n")
        release_lines = [
            line for line in text.splitlines() if re.match(r"^## \d+\.\d+\.\d+", line)
        ]
        assert release_lines
        assert all(heading.fullmatch(line) for line in release_lines)


def test_changelogs_release_task_transfer_v3_on_actual_date() -> None:
    release_heading = "## 0.1.36 - 2026-07-16 - Task Transfer UX And Storage V3"
    for path in CHANGELOGS:
        release = normalized_prose(markdown_section(path, release_heading))
        assert "task transfer" in release
        assert "fresh" in release and "selection" in release
        assert "extension" in release and "project" in release
        assert "version-3" in release and "tasks/" in release
        assert "all-or-nothing" in release
        assert "windows x64" in release and "macos apple silicon" in release


def test_0_1_38_changelogs_describe_deterministic_task_transfer_contract() -> None:
    release_heading = (
        "## 0.1.38 - 2026-07-23 - Deterministic Task Import Registration"
    )
    for path in CHANGELOGS:
        entries = [
            entry.casefold()
            for entry in re.findall(
                r"^- (?P<entry>.+)$",
                markdown_section(path, release_heading),
                re.MULTILINE,
            )
        ]
        assert any(
            "one-project operations" in entry
            and "all eligible tasks initially selected" in entry
            and "review transfer status cross-project and read-only" in entry
            for entry in entries
        )
        assert any("defensive one-project enforcement" in entry for entry in entries)
        assert any(
            "official codex `app-server` using targeted reads" in entry for entry in entries
        )
        assert any(
            "safe after registration failures" in entry
            and "repeated import retry registration" in entry
            for entry in entries
        )
        assert any(
            "cached-task-list refresh guidance" in entry
            and "no-model, no-direct-sqlite, and no-private-registry-write guarantees" in entry
            for entry in entries
        )


def test_changelogs_use_exact_historical_release_dates() -> None:
    assert release_dates(CHANGELOGS[0]) == ROOT_RELEASE_DATES
    assert release_dates(CHANGELOGS[1]) == {
        version: ROOT_RELEASE_DATES[version] for version in EXTENSION_RELEASE_VERSIONS
    }


@pytest.mark.parametrize("changelog", CHANGELOGS, ids=("repository", "extension"))
def test_1_5_0_changelogs_describe_verified_backup_boundary(changelog: Path) -> None:
    section = normalized_prose(
        markdown_section(
            changelog,
            "## 1.5.0 - 2026-08-07 - Verified Task Backups",
        )
    )

    assert ".codex-task-backup" in section
    assert "verify" in section and "atomic" in section
    assert "salvage" in section and "recovery-ready" in section
    assert "does not restore" in section


@pytest.mark.parametrize("changelog", CHANGELOGS, ids=("repository", "extension"))
def test_1_0_0_changelogs_describe_stable_promotion_and_tooltip_fix(
    changelog: Path,
) -> None:
    section = normalized_prose(
        markdown_section(
            changelog,
            "## 1.0.0 - 2026-08-03 - Stable Marketplace Release",
        )
    )

    assert "stable" in section and "preview" in section
    assert "project breakdown" in section and "model mix" in section
    assert "tooltip" in section and "clipped" in section


@pytest.mark.parametrize("changelog", CHANGELOGS, ids=("repository", "extension"))
def test_1_1_0_changelogs_describe_incremental_cache_release(changelog: Path) -> None:
    section = normalized_prose(
        markdown_section(
            changelog,
            "## 1.1.0 - 2026-08-03 - Incremental Usage Cache",
        )
    )

    assert "schema 4" in section
    assert "one pass" in section
    assert "Loaded in".casefold() in section


@pytest.mark.parametrize("changelog", CHANGELOGS, ids=("repository", "extension"))
def test_0_1_42_changelogs_describe_parallel_refresh_contract(
    changelog: Path,
) -> None:
    section = markdown_section(
        changelog,
        "## 0.1.42 - 2026-07-31 - Faster Root-Task Transfer And Usage Refresh",
    )
    expected_bullets = (
        "Listed only active user-visible root tasks in Task Transfer while keeping subagent usage in dashboard totals.",
        "Deferred complete task hashing and conflict planning until after selection by replacing browse-time usage parsing and all-task hashing with metadata-only inventory.",
        "Skipped JSON decoding for irrelevant Codex events without changing usage totals, pricing, cache schema, or aggregation behavior.",
        "Refreshed invalidated usage caches with at most four whole-file worker processes and parent-only eight-file atomic commits, retaining complete prior generations on failure without adding offsets, range pruning, or schema changes.",
    )
    assert tuple(
        line.removeprefix("- ")
        for line in section.splitlines()
        if line.startswith("- ")
    ) == expected_bullets


@pytest.mark.parametrize("changelog", CHANGELOGS, ids=("repository", "extension"))
def test_0_1_41_changelog_describes_effective_dated_price_reduction(
    changelog: Path,
) -> None:
    section = normalized_prose(
        markdown_section(
            changelog,
            "## 0.1.41 - 2026-07-30 - Reduced Terra And Luna API Pricing",
        )
    )

    assert "july 31, 2026" in section
    assert "historical" in section and "original rates" in section
    assert "sol" in section and "unchanged" in section
    assert "codex credit" in section and "unchanged" in section


def test_current_support_docs_use_stable_task_transfer_language() -> None:
    for support_document in SUPPORT_DOCS:
        support = support_document.read_text(encoding="utf-8").casefold()
        assert "preview" not in support
        assert "task transfer" in support
        assert "sync issues" not in support
