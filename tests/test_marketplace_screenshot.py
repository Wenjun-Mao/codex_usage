from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from codex_usage.report_breakdown import build_report_breakdown

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "generate_marketplace_screenshot.py"


def _load_screenshot_module():
    assert SCRIPT_PATH.is_file(), "marketplace screenshot generator is missing"
    spec = importlib.util.spec_from_file_location("marketplace_screenshot", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_synthetic_records_cover_roles_models_other_and_safe_paths() -> None:
    screenshot_module = _load_screenshot_module()

    records = screenshot_module.build_synthetic_records()

    assert {record.usage_role for record in records} == {"root", "subagent"}
    assert len({record.project_key for record in records}) >= 2
    assert len({record.model for record in records}) >= 8
    assert all("/Users/" not in str(record.file_path) for record in records)
    assert all("C:\\Users\\" not in str(record.file_path) for record in records)
    assert build_report_breakdown(records).visual_models[-1].label == "Other"


def test_synthetic_report_uses_production_role_model_markup(tmp_path: Path) -> None:
    screenshot_module = _load_screenshot_module()
    destination = tmp_path / "dashboard.html"

    screenshot_module.render_synthetic_report(destination)

    html = destination.read_text(encoding="utf-8")
    assert 'data-report-section="task-storage"' in html
    assert "Root task JSONL" in html
    assert "Structured subagents" in html
    assert 'data-report-section="project-breakdown"' in html
    assert ">Root tasks<" in html
    assert ">Subagents<" in html
    assert "model-color-slot-7" in html
    assert "<script" not in html
    assert " src=" not in html
    assert " href=" not in html


def test_synthetic_storage_snapshot_covers_root_and_descendant_sizes() -> None:
    screenshot_module = _load_screenshot_module()

    snapshot = screenshot_module.build_synthetic_storage_snapshot()

    assert snapshot.task_tree_count == 4
    assert snapshot.corpus_bytes == sum(tree.total_bytes for tree in snapshot.task_trees)
    assert any(tree.is_large_root for tree in snapshot.task_trees)
    assert any(tree.is_large_tree for tree in snapshot.task_trees)
    assert all(tree.root_bytes and tree.descendant_bytes for tree in snapshot.task_trees)
    assert sum(tree.share for tree in snapshot.task_trees) == 1.0


def test_check_mode_does_not_replace_tracked_screenshot(monkeypatch) -> None:
    screenshot_module = _load_screenshot_module()
    original = screenshot_module.SCREENSHOT_PATH.read_bytes()
    validated_paths: list[Path] = []

    def capture(_report_path: Path, output_path: Path) -> None:
        output_path.write_bytes(b"temporary screenshot")

    monkeypatch.setattr(screenshot_module, "capture_marketplace_screenshot", capture)
    monkeypatch.setattr(
        screenshot_module,
        "validate_screenshot",
        lambda path: validated_paths.append(path),
    )

    assert screenshot_module.main(["--check"]) == 0
    assert screenshot_module.SCREENSHOT_PATH.read_bytes() == original
    assert len(validated_paths) == 1
    assert validated_paths[0] != screenshot_module.SCREENSHOT_PATH


def test_browser_geometry_uses_playwright_box_mappings() -> None:
    screenshot_module = _load_screenshot_module()

    assert screenshot_module._box_values({"x": 10, "y": 20, "width": 30, "height": 40}) == (
        10,
        20,
        30,
        40,
    )


def test_visible_scroll_metrics_ignore_hidden_sections() -> None:
    screenshot_module = _load_screenshot_module()
    metrics = [
        {"clientWidth": 0, "scrollWidth": 0},
        {"clientWidth": 672, "scrollWidth": 672},
    ]

    assert screenshot_module._visible_scroll_metrics(metrics) == [metrics[1]]


def test_tooltip_visibility_gate_rejects_ancestor_clipping_and_missed_hit_tests() -> None:
    screenshot_module = _load_screenshot_module()
    tooltip = {
        "x": 120,
        "y": 80,
        "width": 160,
        "height": 40,
        "clipping_ancestors": ["project-role-group"],
        "hit_inside": True,
    }

    assert "project-role-group" in screenshot_module._tooltip_visibility_error(
        tooltip, viewport_width=720
    )

    tooltip["clipping_ancestors"] = []
    tooltip["hit_inside"] = False
    assert "hit-testing" in screenshot_module._tooltip_visibility_error(
        tooltip, viewport_width=720
    )


def test_clear_tooltip_interaction_blurs_focus_and_moves_the_pointer() -> None:
    screenshot_module = _load_screenshot_module()

    class FakeMouse:
        def __init__(self) -> None:
            self.positions: list[tuple[int, int]] = []

        def move(self, x: int, y: int) -> None:
            self.positions.append((x, y))

    class FakePage:
        def __init__(self) -> None:
            self.mouse = FakeMouse()
            self.scripts: list[str] = []
            self.waits: list[int] = []

        def evaluate(self, script: str) -> None:
            self.scripts.append(script)

        def wait_for_timeout(self, timeout: int) -> None:
            self.waits.append(timeout)

    page = FakePage()

    screenshot_module._clear_tooltip_interaction(page)

    assert page.mouse.positions == [(0, 0)]
    assert page.scripts == ["document.activeElement?.blur()"]
    assert page.waits == [100]
