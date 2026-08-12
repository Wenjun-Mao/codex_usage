from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


def _validate_browser_layout(page: Page, viewport_width: int, view: str) -> None:
    _validate_view_layout(page, view)
    if view == "task-storage":
        _validate_storage_tooltips(page, viewport_width)
    else:
        _validate_focused_tooltips(page, viewport_width)
        _validate_project_track_geometry(page)
        _validate_role_group_geometry(page)
    _validate_scroll_containers(page, view)


def _validate_view_layout(page: Page, view: str) -> None:
    visible_views = page.locator(".report-view:visible")
    if visible_views.count() != 1:
        raise RuntimeError("expected exactly one visible report view")
    if visible_views.first.get_attribute("data-report-view") != view:
        raise RuntimeError(f"unexpected visible report view for {view}")
    tabs = page.locator(".report-view-tab")
    first = tabs.nth(0).bounding_box()
    second = tabs.nth(1).bounding_box()
    if first is None or second is None or first["x"] + first["width"] > second["x"]:
        raise RuntimeError("report view tabs overlap")


def _validate_focused_tooltips(page: Page, viewport_width: int) -> None:
    segments = page.locator(".model-segment")
    segment_count = segments.count()
    if segment_count < 2:
        raise RuntimeError("expected at least two model segments")
    for index in (0, segment_count - 1):
        segment = segments.nth(index)
        segment.hover()
        _validate_visible_tooltip(segment, viewport_width, interaction="hovered")
        segment.focus()
        page.wait_for_timeout(50)
        _validate_visible_tooltip(segment, viewport_width, interaction="focused")


def _validate_storage_tooltips(page: Page, viewport_width: int) -> None:
    stacks = page.locator(".storage-stack")
    stack_count = stacks.count()
    if stack_count < 2:
        raise RuntimeError("expected at least two task storage bars")
    for index in (0, stack_count - 1):
        stack = stacks.nth(index)
        stack.hover()
        _validate_visible_tooltip(stack, viewport_width, interaction="hovered storage")
        stack.focus()
        page.wait_for_timeout(50)
        _validate_visible_tooltip(stack, viewport_width, interaction="focused storage")


def _validate_visible_tooltip(
    segment: Locator, viewport_width: int, *, interaction: str
) -> None:
    diagnostics = segment.locator(".chart-tooltip").evaluate(
        """
        tooltip => {
          const rect = tooltip.getBoundingClientRect();
          const clippingAncestors = [];
          for (let ancestor = tooltip.parentElement; ancestor; ancestor = ancestor.parentElement) {
            const style = getComputedStyle(ancestor);
            const ancestorRect = ancestor.getBoundingClientRect();
            const clipsX = style.overflowX !== "visible";
            const clipsY = style.overflowY !== "visible";
            const clippedX = clipsX && (rect.left < ancestorRect.left || rect.right > ancestorRect.right);
            const clippedY = clipsY && (rect.top < ancestorRect.top || rect.bottom > ancestorRect.bottom);
            if (clippedX || clippedY) {
              clippingAncestors.push(ancestor.className || ancestor.tagName);
            }
          }
          const originalPointerEvents = tooltip.style.pointerEvents;
          tooltip.style.pointerEvents = "auto";
          const hit = document.elementFromPoint(
            rect.left + Math.min(rect.width / 2, Math.max(1, rect.width - 1)),
            rect.top + Math.min(rect.height / 2, Math.max(1, rect.height - 1)),
          );
          tooltip.style.pointerEvents = originalPointerEvents;
          return {
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
            clipping_ancestors: clippingAncestors,
            hit_inside: Boolean(hit && tooltip.contains(hit)),
          };
        }
        """
    )
    if not isinstance(diagnostics, dict):
        raise RuntimeError(f"{interaction} model tooltip is missing diagnostics")
    if error := _tooltip_visibility_error(diagnostics, viewport_width=viewport_width):
        raise RuntimeError(f"{interaction} model tooltip {error}")


def _tooltip_visibility_error(
    tooltip: dict[str, object], *, viewport_width: int
) -> str | None:
    tooltip_x = float(tooltip["x"])
    tooltip_y = float(tooltip["y"])
    tooltip_width = float(tooltip["width"])
    tooltip_height = float(tooltip["height"])
    clipping_ancestors = tooltip["clipping_ancestors"]
    if not isinstance(clipping_ancestors, list):
        return "has invalid ancestor clipping diagnostics"
    if clipping_ancestors:
        ancestors = ", ".join(str(ancestor) for ancestor in clipping_ancestors)
        return f"is clipped by ancestor overflow: {ancestors}"
    if not tooltip.get("hit_inside"):
        return "is not reachable by tooltip hit-testing"
    if (
        tooltip_y < 0
        or tooltip_x < 0
        or tooltip_x + tooltip_width > viewport_width
        or tooltip_height <= 0
    ):
        return "escapes its visible chart area"
    return None


def _clear_tooltip_interaction(page: Page) -> None:
    page.mouse.move(0, 0)
    page.evaluate("document.activeElement?.blur()")
    page.wait_for_timeout(100)


def _validate_role_group_geometry(page: Page) -> None:
    groups = page.locator(".project-role-group")
    if groups.count() == 0:
        raise RuntimeError("expected project role groups")
    for index in range(groups.count()):
        group = groups.nth(index)
        group_box = group.bounding_box()
        stack_box = _ancestor(group, "project-role-stack").bounding_box()
        if group_box is None or stack_box is None:
            raise RuntimeError("project role group is missing geometry")
        group_x, group_y, group_width, group_height = _box_values(group_box)
        stack_x, stack_y, stack_width, stack_height = _box_values(stack_box)
        if (
            group_width <= 0
            or group_height <= 0
            or group_x < stack_x
            or group_y < stack_y
            or group_x + group_width > stack_x + stack_width
            or group_y + group_height > stack_y + stack_height
        ):
            raise RuntimeError("project role group escapes its project role stack")


def _validate_project_track_geometry(page: Page) -> None:
    tracks = page.locator(".project-track")
    track_widths = [
        _box_values(box)[2]
        for index in range(tracks.count())
        if (box := tracks.nth(index).bounding_box()) is not None
    ]
    if not track_widths:
        raise RuntimeError("expected project tracks")
    if max(track_widths) - min(track_widths) > 0.5:
        raise RuntimeError("project tracks do not share one chart width")

    clipped_labels = page.locator(".project-role-heading-label").evaluate_all(
        """
        labels => labels.filter(label => {
          const rect = label.getBoundingClientRect();
          const range = document.createRange();
          range.selectNodeContents(label);
          const textRect = range.getBoundingClientRect();
          return textRect.left < rect.left - 0.5 || textRect.right > rect.right + 0.5;
        }).map(label => label.textContent)
        """
    )
    if clipped_labels:
        raise RuntimeError(f"project role labels are clipped: {clipped_labels}")


def _validate_scroll_containers(page: Page, view: str) -> None:
    metrics = page.locator(".tooltip-chart-scroll").evaluate_all(
        "elements => elements.map(({clientWidth, scrollWidth}) => ({clientWidth, scrollWidth}))"
    )
    visible_metrics = _visible_scroll_metrics(metrics)
    expected_chart_count = 0 if view == "task-storage" else 2
    if len(visible_metrics) != expected_chart_count or any(
        item["scrollWidth"] < item["clientWidth"] for item in visible_metrics
    ):
        raise RuntimeError("chart tooltip scroll containers have invalid geometry")
    storage_metrics = page.locator(".storage-chart-scroll").evaluate_all(
        "elements => elements.map(({clientWidth, scrollWidth}) => ({clientWidth, scrollWidth}))"
    )
    visible_storage_metrics = _visible_scroll_metrics(storage_metrics)
    expected_storage_count = 1 if view == "task-storage" else 0
    if len(visible_storage_metrics) != expected_storage_count or any(
        item["scrollWidth"] < item["clientWidth"] for item in visible_storage_metrics
    ):
        raise RuntimeError("task storage scroll container has invalid geometry")


def _ancestor(locator: Locator, class_name: str) -> Locator:
    return locator.locator(
        f"xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' {class_name} ')]"
    ).first


def _box_values(box: dict[str, float]) -> tuple[float, float, float, float]:
    return box["x"], box["y"], box["width"], box["height"]


def _visible_scroll_metrics(metrics: list[dict[str, int]]) -> list[dict[str, int]]:
    return [item for item in metrics if item["clientWidth"] > 0]
