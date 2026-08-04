from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs/adr/0019-bounded-parallel-cache-refresh.md"
ADR_INDEX = ROOT / "docs/adr/README.md"
INCREMENTAL_ADR = ROOT / "docs/adr/0020-incremental-range-aware-usage-cache.md"


def normalized_prose(value: str) -> str:
    return " ".join(value.casefold().split())


def test_parallel_refresh_adr_locks_the_recovery_contract() -> None:
    assert ADR.exists(), "ADR 0019 must document the parallel refresh contract"
    adr = ADR.read_text(encoding="utf-8")
    prose = normalized_prose(adr)
    index = normalized_prose(ADR_INDEX.read_text(encoding="utf-8"))

    assert re.findall(r"^## (.+)$", adr, re.MULTILINE) == [
        "Status",
        "Context",
        "Decision",
        "Rejected Alternatives",
        "Consequences And Guardrails",
    ]
    for term in (
        "os.process_cpu_count()",
        "four",
        "spawn",
        "raw candidates",
        "one global verification cache",
        "parent process",
        "state_5.sqlite",
        "eight",
        "complete file generation",
        "serial fallback",
        "infrastructure",
        "per-file error",
        "no byte offset",
        "schema version 3",
        "macOS Apple Silicon",
        "Windows x64",
        "pre-publish",
    ):
        assert term.casefold() in prose, term

    for term in (
        "threads",
        "range pruning",
        "transition schema caching",
        "worker path verification",
        "append checkpoints",
        "source/frozen pid-overlap proof",
        "child sqlite guards",
        "oracle equivalence",
        "manual non-publishing dual-native workflow before tag",
    ):
        assert term.casefold() in prose, term

    assert "0018" in index
    assert "0019" in index


def test_incremental_cache_docs_lock_the_1_1_0_contract() -> None:
    documents = (
        INCREMENTAL_ADR,
        ROOT / "README.md",
        ROOT / "extensions/vscode/README.md",
    )
    prose = "\n".join(path.read_text(encoding="utf-8") for path in documents)

    for phrase in (
        "schema 4",
        "disposable derived data",
        "one pass",
        "per task",
        "range-aware",
        "Loaded in",
        "latest request",
        "complete file generation",
        "macOS Apple Silicon",
        "Windows x64",
    ):
        assert phrase.casefold() in prose.casefold(), phrase
    assert "0020-incremental-range-aware-usage-cache.md" in ADR_INDEX.read_text(
        encoding="utf-8"
    )
