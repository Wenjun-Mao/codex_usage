from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCS = (ROOT / "README.md", ROOT / "extensions/vscode/README.md")
ADR_0014 = ROOT / "docs/adr/0014-manual-task-transfer.md"
ADR_INDEX = ROOT / "docs/adr/README.md"


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
def test_current_docs_explain_task_transfer_retirement_and_native_handoff(path: Path) -> None:
    section = normalized_prose(markdown_section(path, "## Task Transfer"))

    for phrase in (
        "retired in **2.13.0**",
        "no longer supported",
        "native host handoff",
        "connected hosts",
        "matching saved git projects",
        "interrupt active work",
        "offline-recovery",
        "non-git migration",
        "not a backup",
    ):
        assert phrase in section, (path, phrase)


@pytest.mark.parametrize("path", CURRENT_DOCS, ids=("repository", "companion"))
def test_current_docs_define_retired_transfer_data_preservation(path: Path) -> None:
    section = normalized_prose(markdown_section(path, "## Task Transfer"))

    for phrase in (
        "existing chats",
        "transfer folders",
        "exported files",
        "paired-transfer state",
        "untouched",
        "inert legacy settings",
        "not accessed",
        "no automatic migration, reimport or cleanup",
        "not guaranteed compatible",
    ):
        assert phrase in section, (path, phrase)


def test_repository_docs_define_persistent_capture_contract() -> None:
    text = normalized_prose(CURRENT_DOCS[0].read_text(encoding="utf-8"))

    for phrase in (
        "persistent local history",
        "default schedule runs every 15 minutes",
        "open zero jsonls",
        "guard windows and the new tail",
        "capture usage before manually deleting",
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
    assert "separate platform vsix packages" in platforms
    assert "macos 13" in platforms and "windows 10" in platforms
    assert "linux" in platforms and "not supported" in platforms
    assert "retire legacy background service" in prose
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


def test_retired_transfer_sources_are_absent_but_shared_runtime_remains() -> None:
    for name in ("agent_transfer.py", "sync_cli.py", "codex_registration.py", "desktop_binding.py"):
        assert not (ROOT / "src/codex_usage" / name).exists()
    assert not list((ROOT / "src/codex_usage/sync").glob("*.py"))
    assert (ROOT / "src/codex_usage/codex_runtime.py").is_file()
    assert (ROOT / "src/codex_usage/ledger_sync.py").is_file()
    assert (ROOT / "src/codex_usage/ledger_transition_sync.py").is_file()


def test_release_docs_require_platform_vsix_and_handoff_gate() -> None:
    prose = normalized_prose(
        (ROOT / "docs/release.md").read_text(encoding="utf-8")
    )

    for phrase in (
        "non-publishing platform gate",
        "both platform vsix jobs must pass before publication",
        "legacy handoff acceptance",
        "disposable `codex_home`",
        "exactly one matching",
        "clean vsix install",
    ):
        assert phrase in prose, phrase


def test_current_product_docs_describe_extension_lifecycle_and_handoff() -> None:
    for path in CURRENT_DOCS:
        prose = normalized_prose(path.read_text(encoding="utf-8"))
        assert "legacy" in prose and "handoff" in prose, path
        assert "while vs code is open" in prose, path

    repository = normalized_prose(CURRENT_DOCS[0].read_text(encoding="utf-8"))
    assert "marketplace extension updates through vs code" in repository
    assert "quota snapshots missed" in repository


def test_adr_0014_keeps_manual_transfer_guardrails() -> None:
    assert "0076-retire-task-transfer.md" in ADR_0014.read_text(encoding="utf-8")
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
