from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "generate_marketplace_screenshot.py"
FIXTURE_PATH = ROOT / "apps" / "desktop" / "src" / "fixtures.ts"


def _load_screenshot_module():
    assert SCRIPT_PATH.is_file(), "marketplace screenshot generator is missing"
    spec = importlib.util.spec_from_file_location("marketplace_screenshot", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generator_targets_built_native_frontend_and_two_views() -> None:
    module = _load_screenshot_module()
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert module.DESKTOP_ROOT == ROOT / "apps" / "desktop"
    assert module.USAGE_SCREENSHOT_PATH.name == "native-usage-synthetic.png"
    assert module.STORAGE_SCREENSHOT_PATH.name == "native-storage-synthetic.png"
    assert module.VIEWPORT == {"width": 1440, "height": 900}
    assert module.NARROW_VIEWPORT["width"] == 760
    assert '"npm", "run", "build"' in source
    assert 'name="Token Usage"' in source
    assert 'name="Task Storage"' in source
    assert "frame_locator" in source


def test_native_fixture_is_deterministic_and_synthetic() -> None:
    fixture = FIXTURE_PATH.read_text(encoding="utf-8")

    assert 'FIXTURE_NOW = new Date("2026-09-02T16:00:00.000Z")' in fixture
    assert "new Date(Date.now()" not in fixture
    assert "Ship native persistent collector" in fixture
    assert "Task Transfer verification" in fixture
    assert "/Users/wjmao" not in fixture
    assert "C:\\Users\\wjmao" not in fixture


def test_check_mode_never_replaces_tracked_images(monkeypatch) -> None:
    module = _load_screenshot_module()
    originals = {
        module.USAGE_SCREENSHOT_PATH: module.USAGE_SCREENSHOT_PATH.read_bytes(),
        module.STORAGE_SCREENSHOT_PATH: module.STORAGE_SCREENSHOT_PATH.read_bytes(),
    }
    captured: list[tuple[Path, Path]] = []

    def render(usage_path: Path, storage_path: Path) -> None:
        captured.append((usage_path, storage_path))
        usage_path.write_bytes(b"temporary usage")
        storage_path.write_bytes(b"temporary storage")

    monkeypatch.setattr(module, "_render_capture_and_validate", render)

    assert module.main(["--check"]) == 0
    assert len(captured) == 1
    assert all(path not in originals for path in captured[0])
    assert all(path.read_bytes() == contents for path, contents in originals.items())


def test_screenshot_validator_rejects_wrong_dimensions(tmp_path: Path) -> None:
    module = _load_screenshot_module()
    path = tmp_path / "small.png"
    Image.new("RGB", (20, 20), color=(10, 20, 30)).save(path)

    try:
        module.validate_screenshot(path)
    except RuntimeError as error:
        assert "dimensions" in str(error)
    else:
        raise AssertionError("a non-Marketplace image size should fail validation")
