from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
READMES = (ROOT / "README.md", ROOT / "extensions/vscode/README.md")
CHANGELOGS = (ROOT / "CHANGELOG.md", ROOT / "extensions/vscode/CHANGELOG.md")
ADR_19 = ROOT / "docs/adr/0019-bounded-parallel-cache-refresh.md"
ADR_20 = ROOT / "docs/adr/0020-incremental-range-aware-usage-cache.md"
ADR_22 = ROOT / "docs/adr/0022-guarded-append-parser-checkpoints.md"


def markdown_section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, (path, heading)
    return match.group("body")


@pytest.mark.parametrize("readme", READMES, ids=("repository", "extension"))
def test_readmes_describe_schema_6_append_contract(readme: Path) -> None:
    text = readme.read_text(encoding="utf-8").casefold()

    assert "schema 6" in text
    assert "old-boundary digest" in text
    assert "new tail" in text
    assert "append fallbacks" in text
    assert "source bytes read" in text
    assert "reparsing complete files from byte zero" not in text


def test_guarded_append_adr_records_tradeoff_and_supersession() -> None:
    adr = ADR_22.read_text(encoding="utf-8").casefold()

    assert "148 gb" in adr and "2,509 jsonl files" in adr
    assert "cryptographic verification" in adr
    assert "middle-of-file in-place edit" in adr
    assert "outside the fast-path contract" in adr
    assert "partially superseded" in ADR_19.read_text(encoding="utf-8").casefold()
    assert "partially superseded" in ADR_20.read_text(encoding="utf-8").casefold()
    assert "adr 0022" in (ROOT / "docs/adr/README.md").read_text(
        encoding="utf-8"
    ).casefold()


@pytest.mark.parametrize("changelog", CHANGELOGS, ids=("repository", "extension"))
def test_1_3_0_changelogs_describe_performance_contract(changelog: Path) -> None:
    release = markdown_section(
        changelog,
        "## 1.3.0 - 2026-08-07 - Guarded Append Performance",
    ).casefold()

    for phrase in (
        "schema 6",
        "tail-only",
        "4 kib",
        "session_meta",
        "valued each usage record once",
        "source bytes read",
    ):
        assert phrase in release, (changelog, phrase)
