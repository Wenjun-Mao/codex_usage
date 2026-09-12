"""Ledger-only image activity valuation and report grouping.

Image operations deliberately remain outside language usage aggregation.  This
module is the narrow bridge from durable image-event rows to presentation: it
selects retained model evidence, values only complete upstream telemetry, and
groups the resulting operations without retaining image content.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from codex_usage.image_aggregation import (
    ImageActivitySummary,
    ValuedImageOperation,
    summarize_image_operations,
)
from codex_usage.image_models import (
    ImageModelFamily,
    ImageModelVariant,
    ImageOperation,
    resolve_image_model_evidence,
)
from codex_usage.image_pricing import value_image_usage


@dataclass(frozen=True, slots=True)
class ImageReportModel:
    label: str
    summary: ImageActivitySummary


@dataclass(frozen=True, slots=True)
class ImageReportProject:
    project_key: str
    label: str
    summary: ImageActivitySummary


@dataclass(frozen=True, slots=True)
class ImageReportCoverage:
    """Ledger-derived historical coverage shown alongside image activity."""

    complete: bool = True
    artifacts_total: int = 0
    tasks_total: int = 0
    tasks_completed: int = 0
    tasks_unavailable: int = 0

    @property
    def pending_tasks(self) -> int:
        return max(0, self.tasks_total - self.tasks_completed - self.tasks_unavailable)


@dataclass(frozen=True, slots=True)
class ImageReport:
    summary: ImageActivitySummary
    models: tuple[ImageReportModel, ...]
    projects: tuple[ImageReportProject, ...]
    coverage: ImageReportCoverage = ImageReportCoverage()


def build_image_report(
    operations: Iterable[ImageOperation],
    *,
    coverage: ImageReportCoverage | None = None,
) -> ImageReport:
    """Value and group selected durable operations without touching source files."""
    valued = tuple(_value(operation) for operation in operations)
    by_model: dict[str, list[ValuedImageOperation]] = defaultdict(list)
    by_project: dict[tuple[str, str], list[ValuedImageOperation]] = defaultdict(list)
    for item in valued:
        by_model[_model_label(item.operation)].append(item)
        by_project[(item.operation.project_key, item.operation.project_label)].append(item)

    models = tuple(
        ImageReportModel(label, summarize_image_operations(items))
        for label, items in sorted(
            by_model.items(), key=lambda item: (-len(item[1]), item[0])
        )
    )
    projects = tuple(
        ImageReportProject(
            key,
            label or "Unassigned",
            summarize_image_operations(items),
        )
        for (key, label), items in sorted(
            by_project.items(),
            key=lambda item: (-len(item[1]), item[0][1].casefold(), item[0][0]),
        )
    )
    return ImageReport(
        summarize_image_operations(valued),
        models,
        projects,
        coverage or ImageReportCoverage(),
    )


def _value(operation: ImageOperation) -> ValuedImageOperation:
    resolved = resolve_image_model_evidence(operation.evidence)
    timestamp = datetime.fromtimestamp(operation.timestamp_us / 1_000_000, tz=UTC)
    return ValuedImageOperation(
        operation,
        value_image_usage(
            operation.usage,
            resolved.model,
            at=timestamp,
            evidence_conflicts=resolved.has_conflict,
        ),
    )


def _model_label(operation: ImageOperation) -> str:
    model = resolve_image_model_evidence(operation.evidence).model
    if model.family is ImageModelFamily.GPT_IMAGE_2_5:
        if model.variant is ImageModelVariant.SUNBURST:
            return "GPT Image 2.5 Sunburst"
        if model.variant is ImageModelVariant.FLARE:
            return "GPT Image 2.5 Flare"
        return "GPT Image 2.5"
    if model.family is ImageModelFamily.GPT_IMAGE_2:
        return "GPT Image 2"
    return "Unresolved image model"
