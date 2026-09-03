from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
READMES = (ROOT / "README.md", ROOT / "extensions/vscode/README.md")
ADR = ROOT / "docs/adr/0027-storage-amplification-analysis-and-rollover.md"
LIFECYCLE_ADR = ROOT / "docs/adr/0031-codex-owned-task-lifecycle.md"
KNOWLEDGE = ROOT / "docs/knowledge/task-storage-amplification.md"


@pytest.mark.parametrize("readme", READMES, ids=("repository", "extension"))
def test_readmes_disclose_storage_analysis_and_lifecycle_boundaries(
    readme: Path,
) -> None:
    text = " ".join(readme.read_text(encoding="utf-8").casefold().split())

    for phrase in (
        "history amplification",
        "at least 1 gib",
        "at least 50%",
        "not analyzed",
        "fork in codex",
        "fresh task with a concise handoff",
        "not a backup",
        "does not create",
    ):
        assert phrase in text, (readme, phrase)


def test_adr_and_knowledge_note_preserve_root_cause_and_guardrails() -> None:
    adr = ADR.read_text(encoding="utf-8").casefold()
    lifecycle = " ".join(
        LIFECYCLE_ADR.read_text(encoding="utf-8").casefold().split()
    )
    knowledge = KNOWLEDGE.read_text(encoding="utf-8").casefold()

    assert "schema 8" in adr and "complete" in adr and "partial" in adr
    assert "at most four" in adr and "atomic" in adr
    assert "superseded by adr 0031" in adr
    assert "tiktok mini games" in knowledge
    assert "plan ebook translation workflow" in knowledge
    assert "turn count" in knowledge and "subagent count" in knowledge
    assert "partial or missing" in knowledge and "must never" in knowledge
    assert "task transfer" in lifecycle and "not a backup" in lifecycle
    assert "existing `.codex-task-backup` files" in lifecycle
    assert "does not automate forking" in lifecycle


def test_adr_index_links_storage_amplification_contract() -> None:
    index = (ROOT / "docs/adr/README.md").read_text(encoding="utf-8")

    assert "[ADR 0027](0027-storage-amplification-analysis-and-rollover.md)" in index
    assert "[ADR 0031](0031-codex-owned-task-lifecycle.md)" in index
