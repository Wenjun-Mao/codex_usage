from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCS = (ROOT / "README.md", ROOT / "extensions/vscode/README.md")
CHANGELOGS = (ROOT / "CHANGELOG.md", ROOT / "extensions/vscode/CHANGELOG.md")
ADR_0014 = ROOT / "docs/adr/0014-manual-task-transfer.md"
CURRENT_TASK_TRANSFER_FIXTURES = (
    ROOT / "scripts/build-windows-exe.ps1",
    ROOT / "scripts/packaged_sync_smoke_validation.py",
    ROOT / "scripts/smoke-test-packaged-sync.py",
    ROOT / "src/codex_usage/sync/planner.py",
    ROOT / "extensions/vscode/test/syncProtocol.test.js",
    ROOT / "tests/packaged_sync_smoke_support.py",
    ROOT / "tests/test_sync_runner_bookkeeping.py",
)

ROOT_RELEASE_DATES = {
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


def release_dates(path: Path) -> dict[str, str]:
    return dict(
        re.findall(
            r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})(?: - .+)?$",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )


def normalized_prose(value: str) -> str:
    return " ".join(value.casefold().split())


def test_current_docs_lead_with_six_step_task_transfer_workflow() -> None:
    for path in CURRENT_DOCS:
        section = markdown_section(path, "## Task Transfer")
        introduction, _, _ = section.partition("1. ")
        introduction = introduction.casefold()
        assert "deliberately moves" in introduction
        assert "token reporting works without task transfer" in introduction
        assert "built-in handoff" in introduction

        numbered_steps = re.findall(r"^(\d+)\. (.+)$", section, re.MULTILINE)
        expected_numbers = [str(number) for number in range(1, 7)]
        assert [number for number, _ in numbered_steps] == expected_numbers
        steps = [step.casefold() for _, step in numbered_steps]
        assert all(
            phrase in steps[0]
            for phrase in ("source computer", "export tasks", "active tasks")
        )
        assert all(
            phrase in steps[1]
            for phrase in ("wait", "filesystem provider", "transfer folder")
        )
        assert all(
            phrase in steps[2]
            for phrase in ("clone or copy", "project checkout", "destination")
        )
        assert all(
            phrase in steps[3]
            for phrase in ("open", "checkout", "vs code", "ide extension")
        )
        assert all(
            phrase in steps[4]
            for phrase in (
                "import tasks",
                "automatic project match",
                "validated local folder",
            )
        )
        assert "reload vs code or restart the codex app" in steps[5]


def test_current_docs_define_durable_transfer_selection_and_mapping() -> None:
    for path in CURRENT_DOCS:
        section = normalized_prose(markdown_section(path, "## Task Transfer"))
        assert "desktop app is not required" in section
        assert "does not clone" in section or "never clones" in section
        assert "destination checkout must already exist" in section
        assert "fresh, empty selection" in section
        assert "review inspects task state without copying files" in section
        assert "task selections" in section and "project mappings" in section
        assert re.search(
            r"neither task selections nor project mappings are saved|"
            r"task selections and project mappings are (?:not|never) saved",
            section,
        )
        assert "imported tasks remain in the transfer folder" in section
        assert "git origin" in section and "wrong origin" in section
        assert "non-git project" in section and "asks for confirmation" in section
        assert re.search(r"only (?:that|the) folder path is remembered", section)


def test_current_docs_require_both_native_v3_packaged_workflow_gates() -> None:
    status_sections = (
        markdown_section(CURRENT_DOCS[0], "## VS Code Preview Packages"),
        markdown_section(CURRENT_DOCS[1], "## Preview Status"),
    )
    for path, section in zip(CURRENT_DOCS, status_sections, strict=True):
        status = normalized_prose(section)
        assert "windows x64" in status
        assert "macos apple silicon" in status
        assert "both" in status
        assert "native" in status and "packaged" in status
        assert "version-3" in status or "v3" in status
        assert "task transfer smoke gates" in status
        assert "release workflow runs" in status
        assert "requires them to pass before publication" in status
        assert "linux packaging is a follow-up" in status
        assert "not a supported target in this release" in status

        text = path.read_text(encoding="utf-8").casefold()
        assert "remain pending" not in text
        assert "windows x64 packaged task transfer passed locally" not in text


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


def test_current_task_transfer_fixtures_use_task_language() -> None:
    forbidden = (
        "Packaged sync smoke",
        "local conversation",
        "Local conversation",
        "_fail_conversation_copy",
        "matching conversation bytes",
    )
    for path in CURRENT_TASK_TRANSFER_FIXTURES:
        text = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in text, (path, phrase)


def test_every_changelog_has_unreleased_and_dated_release_headings() -> None:
    heading = re.compile(
        r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})(?: - .+)?$",
        re.MULTILINE,
    )
    for path in CHANGELOGS:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# Changelog\n\n## Unreleased\n")
        release_lines = [line for line in text.splitlines() if line.startswith("## 0.")]
        assert release_lines
        assert all(heading.fullmatch(line) for line in release_lines)


def test_changelogs_release_task_transfer_v3_on_actual_date() -> None:
    release_heading = "## 0.1.36 - 2026-07-16 - Task Transfer UX And Storage V3"
    for path in CHANGELOGS:
        assert not markdown_section(path, "## Unreleased").strip()
        release = normalized_prose(markdown_section(path, release_heading))
        assert "task transfer" in release
        assert "fresh" in release and "selection" in release
        assert "extension" in release and "project" in release
        assert "version-3" in release and "tasks/" in release
        assert "all-or-nothing" in release
        assert "windows x64" in release and "macos apple silicon" in release


def test_changelogs_use_exact_historical_release_dates() -> None:
    assert release_dates(CHANGELOGS[0]) == ROOT_RELEASE_DATES
    assert release_dates(CHANGELOGS[1]) == {
        version: ROOT_RELEASE_DATES[version] for version in EXTENSION_RELEASE_VERSIONS
    }


def test_adr_0014_supersedes_the_correct_selection_and_transfer_contracts() -> None:
    guardrails = normalized_prose(markdown_section(ADR_0014, "## Guardrails"))
    assert "canonical, nonempty, unique task ids" in guardrails
    assert "exact planner state/action pairs" in guardrails
    assert "sole authoritative destination" in guardrails
    assert "native absolute path to an existing directory" in guardrails
    assert "structured partial-completion result" in guardrails
    assert "completion as unknown" in guardrails

    supersession = normalized_prose(markdown_section(ADR_0014, "## Supersession"))
    assert re.search(
        r"supersedes adr 0012[^.]*exact persisted selection[^.]*setup",
        supersession,
    )
    assert re.search(
        r"supersedes adr 0013[^.]*user presentation[^.]*desktop-root discovery",
        supersession,
    )
    assert (
        "adr 0013's manual-directional data-safety rules remain in force"
        in supersession
    )
    assert all(
        guardrail in supersession
        for guardrail in (
            "manual triggers",
            "directional mutation boundaries",
            "conflict preflight",
            "atomic replacement",
            "backup",
            "observable-boundary validation",
        )
    )
    assert not re.search(r"adr 0013[^.]*persist(?:ed|ent) selection", supersession)
