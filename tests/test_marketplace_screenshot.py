from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "generate_marketplace_screenshot.py"


def _load_module():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("marketplace_screenshot", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generator_uses_extension_renderer_and_public_synthetic_data() -> None:
    module = _load_module()
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    renderer = (ROOT / "scripts/render_extension_marketplace.js").read_text(encoding="utf-8")

    assert module.EXTENSION_ROOT == ROOT / "extensions/vscode"
    assert module.USAGE_SCREENSHOT_PATH.name == "extension-usage-synthetic.png"
    assert module.STORAGE_SCREENSHOT_PATH.name == "extension-storage-synthetic.png"
    assert set(module.USAGE_SCREENSHOT_PATHS) == {
        ("day", "wide"), ("day", "narrow"),
        ("night", "wide"), ("night", "narrow"),
    }
    assert "render_html_report" in source
    assert "decorateUsageReport" in renderer
    assert "renderStorageReport" in renderer
    assert "apps/desktop" not in source + renderer
    records = module.synthetic_records()
    assert len(records) == 96
    assert {record.usage_role for record in records} == {"root", "subagent"}
    assert len({record.project_key for record in records}) == 3
    assert all(not record.file_path.is_absolute() for record in records)
    assert all("/Users/" not in str(record) for record in records)


def test_check_mode_keeps_tracked_images(monkeypatch) -> None:
    module = _load_module()
    originals = {
        path: path.read_bytes()
        for path in (*module.USAGE_SCREENSHOT_PATHS.values(), module.STORAGE_SCREENSHOT_PATH)
    }
    main_image = module.USAGE_SCREENSHOT_PATH.read_bytes()
    captured = []

    def render(usage_paths, storage_path):
        captured.append((usage_paths, storage_path))
        for path in (*usage_paths.values(), storage_path):
            path.write_bytes(b"temporary")

    monkeypatch.setattr(module, "_render_capture_and_validate", render)
    assert module.main(["--check"]) == 0
    assert len(captured) == 1
    assert all(path not in originals for path in captured[0][0].values())
    assert captured[0][1] not in originals
    assert all(path.read_bytes() == contents for path, contents in originals.items())
    assert module.USAGE_SCREENSHOT_PATH.read_bytes() == main_image


def test_screenshot_validator_rejects_wrong_dimensions(tmp_path: Path) -> None:
    module = _load_module()
    path = tmp_path / "small.png"
    Image.new("RGB", (20, 20), color=(10, 20, 30)).save(path)
    try:
        module.validate_screenshot(path)
    except RuntimeError as error:
        assert "dimensions" in str(error)
    else:
        raise AssertionError("a non-Marketplace image size should fail validation")
