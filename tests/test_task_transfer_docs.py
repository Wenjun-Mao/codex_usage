from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCS = (ROOT / "README.md", ROOT / "extensions/vscode/README.md")
ADR_0014 = ROOT / "docs/adr/0014-manual-task-transfer.md"
ADR_INDEX = ROOT / "docs/adr/README.md"
CURRENT_TASK_TRANSFER_FIXTURES = (
    ROOT / "src/codex_usage/agent_transfer.py",
    ROOT / "src/codex_usage/sync/planner.py",
    ROOT / "apps/desktop/src/transferView.ts",
    ROOT / "extensions/vscode/src/taskTransferClient.ts",
    ROOT / "tests/test_agent_transfer.py",
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


@pytest.mark.parametrize("path", CURRENT_DOCS, ids=("repository", "companion"))
def test_current_docs_explain_native_task_transfer_workflow(path: Path) -> None:
    section = normalized_prose(markdown_section(path, "## Task Transfer"))

    for phrase in (
        "one project",
        "transfer folder",
        "no tasks are selected by default",
        "does not clone",
        "local project",
        "fully quit desktop",
        "start codex desktop",
        "reload vs code",
        "review status",
        "without copying",
    ):
        assert phrase in section, (path, phrase)


@pytest.mark.parametrize("path", CURRENT_DOCS, ids=("repository", "companion"))
def test_current_docs_define_transfer_safety_boundary(path: Path) -> None:
    section = normalized_prose(markdown_section(path, "## Task Transfer"))

    for phrase in (
        "conflicts",
        "changed",
        "ambiguous desktop projects",
        "assignment conflicts",
        "targeted codex `app-server` reads",
        "does not start a turn",
        "consume tokens",
        "atomically installs selected jsonls",
        "never edits their content",
        "codex sqlite databases",
        "imported files remain in the transfer folder",
    ):
        assert phrase in section, (path, phrase)


def test_repository_docs_define_persistent_capture_contract() -> None:
    text = normalized_prose(CURRENT_DOCS[0].read_text(encoding="utf-8"))

    for phrase in (
        "persistent local history",
        "default schedule runs every 15 minutes",
        "open zero jsonls",
        "guard windows and the new tail",
        "capture now before manually deleting",
        "forward, backup-protected migrations",
        "one active codex home",
    ):
        assert phrase in text, phrase
    assert "reparsing complete files from byte zero" not in text


def test_companion_readme_is_an_installed_product_guide() -> None:
    path = CURRENT_DOCS[1]
    text = path.read_text(encoding="utf-8")
    prose = normalized_prose(text)
    install = normalized_prose(markdown_section(path, "## Install"))
    platforms = normalized_prose(markdown_section(path, "## Supported Platforms"))

    assert "extensions" in install and "command palette" in install
    assert "no source checkout" in install
    assert "self-contained native app" in platforms
    assert "macos 13" in platforms and "windows 10" in platforms
    assert "linux" in platforms and "not supported" in platforms
    assert "native app remains the home" in prose
    assert "## Development" not in text
    for contributor_detail in (
        "npm install",
        "npm run",
        "`uv`",
        "output/releases",
        "extension development host",
        "schema 8",
        "sqlite remains in the parent process",
    ):
        assert contributor_detail not in prose, contributor_detail


def test_current_docs_explain_storage_analysis_and_codex_owned_lifecycle() -> None:
    for path in CURRENT_DOCS:
        prose = normalized_prose(path.read_text(encoding="utf-8"))
        for phrase in (
            "at least 1 gib",
            "at least 50%",
            "not analyzed",
            "fork in codex",
            "fresh task with a concise handoff",
            "not a backup",
            "does not create, fork, archive, restore, or delete tasks",
        ):
            assert phrase in prose, (path, phrase)


def test_public_readmes_do_not_publish_developer_corpus_measurements() -> None:
    for path in CURRENT_DOCS:
        prose = normalized_prose(path.read_text(encoding="utf-8"))
        for phrase in (
            "the 2026-08-07 audit measured",
            "a 2026-08-08 follow-up had reached",
            "2,525 files",
            "2,563 files",
        ):
            assert phrase not in prose


def test_current_docs_do_not_claim_legacy_sync_or_backup_workflows() -> None:
    forbidden = (
        "Setup required",
        "Pause Sync",
        "Resume Sync",
        "Change Tasks",
        "Clear Sync Setup",
        "Pull Tasks",
        "Push Tasks",
        "Codex Usage: Back Up Task",
        "Codex Usage: Prepare Task Rollover",
        "codex-usage storage backup",
        "codex-usage storage verify",
        "codex-usage storage rollover",
    )
    for path in CURRENT_DOCS:
        text = path.read_text(encoding="utf-8").casefold()
        for phrase in forbidden:
            assert phrase.casefold() not in text, (path, phrase)


def test_current_task_transfer_sources_use_task_language() -> None:
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


def test_release_docs_require_standalone_vsix_and_unsigned_native_gate() -> None:
    prose = normalized_prose(
        (ROOT / "docs/release.md").read_text(encoding="utf-8")
    )

    for phrase in (
        "no apple developer, azure artifact signing, or tauri updater-signing dependency",
        "non-publishing native gate",
        "before publication",
        "macos arm64 pyinstaller",
        "windows x64 pyinstaller",
        "standalone macos apple silicon and windows x64 vsix packages",
        "unsigned native dmg and nsis previews",
        "clean-install acceptance",
    ):
        assert phrase in prose, phrase


def test_current_product_docs_distinguish_marketplace_from_native_preview() -> None:
    for path in CURRENT_DOCS:
        prose = normalized_prose(path.read_text(encoding="utf-8"))
        assert "standalone" in prose, path
        assert "native app" in prose and "preview" in prose, path
        assert "not required" in prose, path

    repository = normalized_prose(CURRENT_DOCS[0].read_text(encoding="utf-8"))
    assert "marketplace extension updates through vs code" in repository
    assert "unsigned native previews do not have a supported automatic update channel" in repository


def test_adr_0014_keeps_manual_transfer_guardrails() -> None:
    guardrails = normalized_prose(markdown_section(ADR_0014, "## Guardrails"))
    for phrase in (
        "canonical, nonempty, unique task ids",
        "exact planner state/action pairs",
        "sole authoritative destination",
        "native absolute path to an existing directory",
        "structured partial-completion result",
        "completion as unknown",
    ):
        assert phrase in guardrails

    supersession = normalized_prose(markdown_section(ADR_0014, "## Supersession"))
    assert "adr 0013's manual-directional data-safety rules remain in force" in supersession
    for phrase in (
        "manual triggers",
        "directional mutation boundaries",
        "conflict preflight",
        "atomic replacement",
        "observable-boundary validation",
    ):
        assert phrase in supersession


def test_adr_index_records_native_ownership_after_manual_transfer() -> None:
    text = ADR_INDEX.read_text(encoding="utf-8")
    assert "[0014](0014-manual-task-transfer.md)" in text
    assert "[ADR 0033](0033-persistent-collector-and-durable-ledger.md)" in text
    assert "[ADR 0034](0034-tauri-native-app-ownership.md)" in text
    assert text.index("0014-manual-task-transfer.md") < text.index(
        "0034-tauri-native-app-ownership.md"
    )
