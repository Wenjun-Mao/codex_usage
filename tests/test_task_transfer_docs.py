from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCS = (ROOT / "README.md", ROOT / "extensions/vscode/README.md")
ADR_0014 = ROOT / "docs/adr/0014-manual-task-transfer.md"
ADR_INDEX = ROOT / "docs/adr/README.md"
CURRENT_TASK_TRANSFER_FIXTURES = (
    ROOT / "scripts/build-windows-exe.ps1",
    ROOT / "scripts/packaged_sync_smoke_validation.py",
    ROOT / "scripts/smoke-test-packaged-sync.py",
    ROOT / "src/codex_usage/sync/planner.py",
    ROOT / "extensions/vscode/test/syncProtocol.test.js",
    ROOT / "tests/packaged_sync_smoke_support.py",
    ROOT / "tests/test_sync_runner_bookkeeping.py",
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


def test_current_docs_describe_observed_cache_write_accounting() -> None:
    for path in CURRENT_DOCS:
        prose = normalized_prose(path.read_text(encoding="utf-8"))
        assert "cache_write_input_tokens" in prose
        assert "cannot include" not in prose
        assert "no distinct cache-write token count" not in prose


def test_current_docs_define_gpt_5_6_cache_write_pricing_contract() -> None:
    for path in CURRENT_DOCS:
        prose = normalized_prose(path.read_text(encoding="utf-8"))
        assert (
            "standard cache-write rates per 1m tokens are: "
            "sol $6.25, terra $2.50, luna $0.25"
        ) in prose
        assert (
            "reduced terra and luna api rates apply from july 31, 2026; "
            "earlier usage keeps the original effective-dated rates"
        ) in prose
        assert "sol ordinary input $10, cache read (cached input) $1, cache write $12.50, output $45" in prose
        assert "terra ordinary input $4, cache read (cached input) $0.40, cache write $5, output $18" in prose
        assert "luna ordinary input $0.40, cache read (cached input) $0.04, cache write $0.50, output $1.80" in prose
        assert "exactly 272,000 input tokens is short-context pricing" in prose
        assert "more than 272,000 input tokens, including 272,001" in prose
        assert "codex credits do not use long-context or api cache-write categories" in prose
        assert "api-equivalent usd figures are estimates, not actual api or codex billing" in prose
        for stale_phrase in ("$10 uncached input", "$5 uncached input", "$2 uncached input"):
            assert stale_phrase not in prose


def test_current_docs_lead_with_seven_step_task_transfer_workflow() -> None:
    for path in CURRENT_DOCS:
        section = markdown_section(path, "## Task Transfer")
        introduction, _, _ = section.partition("1. ")
        introduction = introduction.casefold()
        assert "deliberately moves" in introduction
        assert "token reporting works without task transfer" in introduction
        assert "built-in handoff" in introduction

        numbered_steps = re.findall(r"^(\d+)\. (.+)$", section, re.MULTILINE)
        expected_numbers = [str(number) for number in range(1, 8)]
        assert [number for number, _ in numbered_steps] == expected_numbers
        steps = [step.casefold() for _, step in numbered_steps]
        assert all(
            phrase in steps[0]
            for phrase in ("source computer", "choose transfer folder", "filesystem provider")
        )
        assert all(
            phrase in steps[1]
            for phrase in ("export tasks", "one project", "active tasks")
        )
        assert all(
            phrase in steps[2]
            for phrase in ("wait", "filesystem provider", "transfer folder")
        )
        assert all(
            phrase in steps[3]
            for phrase in ("destination computer", "project checkout", "vs code")
        )
        assert all(
            phrase in steps[4]
            for phrase in ("same transfer folder", "destination computer", "import tasks")
        )
        assert all(
            phrase in steps[5]
            for phrase in ("transferred project", "automatic project match", "validated local folder")
        )
        assert "after successful registration" in steps[6]
        assert "reload vs code or open/restart codex" in steps[6]


def test_public_readmes_do_not_publish_developer_corpus_measurements() -> None:
    for path in CURRENT_DOCS:
        prose = normalized_prose(path.read_text(encoding="utf-8"))
        for developer_specific_phrase in (
            "the 2026-08-07 audit measured",
            "a 2026-08-08 follow-up had reached",
            "2,525 files",
            "2,563 files",
        ):
            assert developer_specific_phrase not in prose


def test_current_docs_explain_storage_actions_as_user_workflows() -> None:
    for path in CURRENT_DOCS:
        prose = normalized_prose(path.read_text(encoding="utf-8"))
        for phrase in (
            "analyze one task tree",
            "choose **analyze** on the task row",
            "choose **maximum** for the smallest, slower archive",
            "recovery-ready or integrity-verified salvage",
            "cannot restore",
            "create a fresh root task in the same codex project",
            "only then archive or delete the old task inside codex",
        ):
            assert phrase in prose


def test_current_docs_define_durable_transfer_selection_and_mapping() -> None:
    for path in CURRENT_DOCS:
        section = normalized_prose(markdown_section(path, "## Task Transfer"))
        assert "desktop app is not required" in section
        assert "does not clone" in section or "never clones" in section
        assert "destination checkout must already exist" in section
        assert "each import or export handles one codex project" in section
        assert "first choose one project" in section
        assert "no tasks are selected by default" in section
        assert "search on the task screen is limited to the chosen project" in section
        assert "use back" in section and "choose a different project" in section
        assert "repeat the operation" in section and "another project" in section
        assert "transfer folder can retain tasks from many projects across separate operations" in section
        assert "review transfer status remains cross-project and does not copy files" in section
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
        assert "targeted `app-server` task-read requests" in section
        assert "does not invoke a model" in section
        assert "never writes codex sqlite or private project registries directly" in section
        assert "re-running import retries registration" in section


def test_current_docs_describe_registration_discovery_and_recovery() -> None:
    troubleshooting_heading = "### Imported files exist but tasks are not visible\n"
    for path in CURRENT_DOCS:
        text = path.read_text(encoding="utf-8")
        transfer = normalized_prose(markdown_section(path, "## Task Transfer"))
        status_heading = (
            "## VS Code Packages"
            if path == ROOT / "README.md"
            else "## Supported Platforms"
        )
        status = normalized_prose(markdown_section(path, status_heading))

        assert "official codex vs code extension" in transfer
        assert "native codex desktop app" in transfer
        assert "and `path`" in transfer
        assert "certified imported files remain safe in place" in transfer
        assert "does not invoke a model, send a prompt, or start a turn" in transfer
        assert "intel macos and windows arm64 are not supported targets" in status

        assert troubleshooting_heading in text
        heading_index = text.index(troubleshooting_heading)
        recovery = text[heading_index + len(troubleshooting_heading) :]
        recovery = recovery.split("\n## ", 1)[0]
        assert "official Codex runtime" in recovery
        assert "Codex Usage output" in recovery
        assert "retry registration" in recovery
        assert "Open or restart Codex" in recovery and "reload VS Code" in recovery


def test_current_docs_require_both_native_v3_packaged_workflow_gates() -> None:
    status_sections = (
        markdown_section(CURRENT_DOCS[0], "## VS Code Packages"),
        markdown_section(CURRENT_DOCS[1], "## Supported Platforms"),
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


@pytest.mark.parametrize("readme", CURRENT_DOCS, ids=("repository", "extension"))
def test_current_docs_describe_guarded_append_recovery(readme: Path) -> None:
    text = readme.read_text(encoding="utf-8").casefold()
    for phrase in (
        "schema 8",
        "unchanged refreshes open no session jsonls",
        "at most four read-only workers",
        "sqlite remains in the parent process",
        "groups of eight files",
        "parser checkpoint",
        "new tail",
    ):
        assert phrase in text, (readme, phrase)

    assert "reparsing complete files from byte zero" not in text


def test_release_docs_require_parallel_audit_and_prepublish_native_gate() -> None:
    text = (ROOT / "docs/release.md").read_text(encoding="utf-8")
    for phrase in (
        "non-parent worker PIDs",
        "overlapping worker spans",
        "no serial fallback",
        "non-publishing native workflow",
        "before creating a release tag or publishing",
    ):
        assert phrase in text


def test_current_product_docs_do_not_describe_the_release_as_preview() -> None:
    for path in CURRENT_DOCS:
        assert "preview" not in path.read_text(encoding="utf-8").casefold(), path

    release_document = (ROOT / "docs/release.md").read_text(encoding="utf-8")
    assert "Marketplace Preview Release Checklist" not in release_document
    assert "Marketplace preview distribution" not in release_document


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


def test_adr_index_keeps_manual_task_transfer_before_token_accounting() -> None:
    rows = re.findall(
        r"^\| \[(\d{4})\]\(([^)]+)\) \| ([^|]+) \|$",
        ADR_INDEX.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert [number for number, _, _ in rows] == sorted(number for number, _, _ in rows)
    assert rows[-4:] == [
        (
            "0014",
            "0014-manual-task-transfer.md",
            "Present the feature as optional Task Transfer with three deliberate operations: Import Tasks, Export Tasks, and Review Transfer Status.",
        ),
        (
            "0015",
            "0015-explicit-token-category-accounting.md",
            "Preserve explicit upstream token categories without reconstructing missing evidence.",
        ),
        (
            "0016",
            "0016-register-imported-tasks-through-codex.md",
            "Register imported tasks through Codex's supported app-server read-repair path.",
        ),
        (
            "0017",
            "0017-one-project-per-transfer-operation.md",
            "Constrain each Import and Export to one Codex project while keeping the transfer folder multi-project.",
        ),
    ]
