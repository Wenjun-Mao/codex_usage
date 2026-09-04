from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
COMPANION_README = ROOT / "extensions" / "vscode" / "README.md"
CHANGELOG_PATHS = (ROOT / "CHANGELOG.md", ROOT / "extensions/vscode/CHANGELOG.md")
RELEASE_CHECKLIST = ROOT / "docs" / "release.md"
USAGE_SCREENSHOT = ROOT / "docs" / "marketplace" / "native-usage-synthetic.png"
STORAGE_SCREENSHOT = ROOT / "docs" / "marketplace" / "native-storage-synthetic.png"


def markdown_section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(heading)}[^\n]*\n(?P<body>.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, (path, heading)
    return match.group("body")


def test_readmes_present_native_usage_and_storage_workflows() -> None:
    root = README.read_text(encoding="utf-8")
    companion = COMPANION_README.read_text(encoding="utf-8")

    for text in (root, companion):
        prose = " ".join(text.split())
        assert "native-usage-synthetic.png" in text
        assert "native-storage-synthetic.png" in text
        assert "Project Breakdown separates root tasks" in prose
        assert "Capture Now" in text
        assert "Task Transfer" in text

    assert "Manual Only" in root
    assert root.index("native-usage-synthetic.png") < root.index("## Install")
    assert root.index("native-storage-synthetic.png") > root.index("## Task Storage")
    assert companion.index("native-usage-synthetic.png") < companion.index(
        "## What You Can Do"
    )
    assert companion.index("native-storage-synthetic.png") > companion.index(
        "## Task Storage"
    )


def test_companion_docs_preserve_the_platform_vsix_runtime_boundary() -> None:
    prose = " ".join(COMPANION_README.read_text(encoding="utf-8").split())

    assert "Each platform-specific VSIX includes the matching collector" in prose
    assert "native app are not runtime requirements" in prose
    assert "separate platform VSIX packages" in prose


def test_native_marketplace_images_are_at_release_dimensions() -> None:
    from PIL import Image

    for path in (USAGE_SCREENSHOT, STORAGE_SCREENSHOT):
        assert path.is_file(), path
        with Image.open(path) as image:
            assert image.size == (1440, 900)


def test_release_checklist_locks_native_visual_gate() -> None:
    checklist = RELEASE_CHECKLIST.read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/package-vsix.yml").read_text(
        encoding="utf-8"
    )

    for phrase in ("1440 x 900", "760", "visually review", "Task Transfer"):
        assert phrase.casefold() in checklist.casefold(), phrase
    for command in (
        "uv run playwright install chromium",
        "uv run python scripts/generate_marketplace_screenshot.py",
        "uv run python scripts/generate_marketplace_screenshot.py --check",
    ):
        assert command in checklist
    assert "uv run playwright install chromium" in workflow
    assert "uv run python scripts/generate_marketplace_screenshot.py --check" in workflow


def test_native_architecture_adrs_record_ownership_and_rejected_alternatives() -> None:
    collector = (
        ROOT / "docs/adr/0033-persistent-collector-and-durable-ledger.md"
    ).read_text(encoding="utf-8").casefold()
    app = (ROOT / "docs/adr/0034-tauri-native-app-ownership.md").read_text(
        encoding="utf-8"
    ).casefold()
    distribution = (
        ROOT / "docs/adr/0036-standalone-extension-and-native-preview.md"
    ).read_text(encoding="utf-8").casefold()
    index = (ROOT / "docs/adr/README.md").read_text(encoding="utf-8")

    assert "0033-persistent-collector-and-durable-ledger.md" in index
    assert "0034-tauri-native-app-ownership.md" in index
    assert "0036-standalone-extension-and-native-preview.md" in index
    for phrase in ("durable", "ledger", "single", "append"):
        assert phrase in collector
    for phrase in ("tauri", "electron", "wails", "qt"):
        assert phrase in app
    for phrase in ("standalone", "parent-bound", "unsigned", "platform vsix"):
        assert phrase in distribution


def test_2_0_0_changelogs_describe_the_breaking_ledger_release() -> None:
    heading = "## 2.0.0 - 2026-09-04"
    for path in CHANGELOG_PATHS:
        text = path.read_text(encoding="utf-8")
        assert text.count("## Unreleased") == 1
        assert text.count(heading) == 1
        release = markdown_section(path, heading).casefold()
        for phrase in ("native", "ledger", "capture", "cli", "standalone"):
            assert phrase in release, (path, phrase)
