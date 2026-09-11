"""Ledger-only, distinct-turn economics for the Usage report.

This module deliberately receives already-valued records.  It must never value
records itself: a report has one pricing pass and the economics view is only a
different aggregation of that same result.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from statistics import median

from codex_usage.aggregation import UsageSummary, ValuedUsageRecord
from codex_usage.model_presentation import model_display_sort_key
from codex_usage.models import TokenUsage
from codex_usage.pricing import CostBreakdown, CreditBreakdown

ALL_PROJECTS_KEY = "__codex_usage_all_projects__"


@dataclass(frozen=True, slots=True)
class TurnCoverage:
    """How much positive ledger usage can participate in turn metrics."""

    total_responses: int
    measured_responses: int
    total_tokens: int
    measured_tokens: int

    @property
    def missing_responses(self) -> int:
        return self.total_responses - self.measured_responses

    @property
    def missing_tokens(self) -> int:
        return self.total_tokens - self.measured_tokens

    @property
    def response_share(self) -> float:
        return _share(self.measured_responses, self.total_responses)

    @property
    def token_share(self) -> float:
        return _share(self.measured_tokens, self.total_tokens)


@dataclass(frozen=True, slots=True)
class TurnMetrics:
    """Metrics whose population is explicitly limited to non-empty turn IDs."""

    turn_count: int
    response_count: int
    token_count: int
    priced_turn_count: int
    priced_response_count: int
    priced_turn_cost_usd: float
    priced_response_cost_usd: float
    average_cost_per_response: float | None
    average_cost_per_turn: float | None
    median_cost_per_turn: float | None

    @property
    def responses_per_turn(self) -> float | None:
        return _ratio(self.response_count, self.turn_count)

    @property
    def tokens_per_turn(self) -> float | None:
        return _ratio(self.token_count, self.turn_count)


@dataclass(frozen=True, slots=True)
class ModelEconomics:
    key: str
    label: str
    total: UsageSummary
    coverage: TurnCoverage
    metrics: TurnMetrics
    token_share: float
    cost_share: float


@dataclass(frozen=True, slots=True)
class ProjectEconomics:
    key: str
    label: str
    total: UsageSummary
    coverage: TurnCoverage
    metrics: TurnMetrics
    models: tuple[ModelEconomics, ...]

    @property
    def is_small_sample(self) -> bool:
        return 0 < self.metrics.turn_count < 5


@dataclass(frozen=True, slots=True)
class ProjectEconomicsReport:
    """A weighted all-project benchmark and its project-level constituents."""

    benchmark: ProjectEconomics
    projects: tuple[ProjectEconomics, ...]


def build_project_economics(
    valued_records: Sequence[ValuedUsageRecord],
) -> ProjectEconomicsReport:
    """Aggregate positive ledger deltas at project-turn and project-model-turn grain.

    A project turn is ``(project_key, session_id, turn_id)``.  A model turn
    adds ``model`` to that key.  Blank turn IDs remain in complete token/cost
    totals and coverage, but never enter turn-derived measures.
    """
    positive_records = tuple(
        valued for valued in valued_records if valued.record.usage.total_tokens > 0
    )
    project_records: dict[str, list[ValuedUsageRecord]] = {}
    project_labels: dict[str, str] = {}
    for valued in positive_records:
        record = valued.record
        project_records.setdefault(record.project_key, []).append(valued)
        project_labels[record.project_key] = record.project_label

    projects = tuple(
        _build_project(
            key,
            project_labels[key],
            project_records[key],
        )
        for key in sorted(
            project_records,
            key=lambda project_key: (
                -_summarize(project_records[project_key]).usage.total_tokens,
                project_key,
            ),
        )
    )
    benchmark = _build_project(
        ALL_PROJECTS_KEY,
        "All projects",
        positive_records,
    )
    report = ProjectEconomicsReport(benchmark=benchmark, projects=projects)
    _validate_report(report)
    return report


def _build_project(
    key: str,
    label: str,
    valued_records: Sequence[ValuedUsageRecord],
) -> ProjectEconomics:
    total = _summarize(valued_records)
    coverage = _coverage(valued_records)
    metrics = _turn_metrics(valued_records, include_model=False)
    models: dict[str, list[ValuedUsageRecord]] = {}
    for valued in valued_records:
        models.setdefault(valued.record.model, []).append(valued)
    model_rows = tuple(
        _build_model(model, models[model], total)
        for model in sorted(models, key=model_display_sort_key)
    )
    return ProjectEconomics(
        key=key,
        label=label,
        total=total,
        coverage=coverage,
        metrics=metrics,
        models=model_rows,
    )


def _build_model(
    model: str,
    valued_records: Sequence[ValuedUsageRecord],
    project_total: UsageSummary,
) -> ModelEconomics:
    total = _summarize(valued_records)
    return ModelEconomics(
        key=model,
        label=model,
        total=total,
        coverage=_coverage(valued_records),
        metrics=_turn_metrics(valued_records, include_model=True),
        token_share=_share(total.usage.total_tokens, project_total.usage.total_tokens),
        cost_share=_share(total.cost.total_usd, project_total.cost.total_usd),
    )


def _coverage(valued_records: Sequence[ValuedUsageRecord]) -> TurnCoverage:
    total = _summarize(valued_records)
    measured = _summarize(
        valued for valued in valued_records if valued.record.turn_id
    )
    return TurnCoverage(
        total_responses=total.record_count,
        measured_responses=measured.record_count,
        total_tokens=total.usage.total_tokens,
        measured_tokens=measured.usage.total_tokens,
    )


def _turn_metrics(
    valued_records: Sequence[ValuedUsageRecord], *, include_model: bool
) -> TurnMetrics:
    measured = tuple(valued for valued in valued_records if valued.record.turn_id)
    turn_summaries: dict[tuple[str, ...], UsageSummary] = {}
    for valued in measured:
        record = valued.record
        turn_key = (record.project_key, record.session_id, record.turn_id)
        if include_model:
            turn_key += (record.model,)
        turn_summaries[turn_key] = _add(turn_summaries.get(turn_key), valued.summary)

    measured_summary = _summarize(measured)
    priced_turns = tuple(
        summary
        for summary in turn_summaries.values()
        if summary.cost.unpriced_tokens == 0
    )
    priced_responses = tuple(
        valued.summary
        for valued in measured
        if valued.summary.cost.unpriced_tokens == 0
    )
    priced_turn_cost_usd = sum(summary.cost.total_usd for summary in priced_turns)
    priced_response_cost_usd = sum(
        summary.cost.total_usd for summary in priced_responses
    )
    return TurnMetrics(
        turn_count=len(turn_summaries),
        response_count=measured_summary.record_count,
        token_count=measured_summary.usage.total_tokens,
        priced_turn_count=len(priced_turns),
        priced_response_count=len(priced_responses),
        priced_turn_cost_usd=priced_turn_cost_usd,
        priced_response_cost_usd=priced_response_cost_usd,
        average_cost_per_response=_ratio(
            priced_response_cost_usd, len(priced_responses)
        ),
        average_cost_per_turn=_ratio(priced_turn_cost_usd, len(priced_turns)),
        median_cost_per_turn=(
            median(summary.cost.total_usd for summary in priced_turns)
            if priced_turns
            else None
        ),
    )


def _summarize(valued_records: Iterable[ValuedUsageRecord]) -> UsageSummary:
    total = _empty_summary()
    for valued in valued_records:
        total = total.add(valued.summary)
    return total


def _add(existing: UsageSummary | None, value: UsageSummary) -> UsageSummary:
    return value if existing is None else existing.add(value)


def _empty_summary() -> UsageSummary:
    return UsageSummary(
        usage=TokenUsage(),
        cost=CostBreakdown(),
        credits=CreditBreakdown(),
        record_count=0,
    )


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return numerator / denominator if denominator else None


def _share(numerator: int | float, denominator: int | float) -> float:
    return numerator / denominator if denominator else 0.0


def _validate_report(report: ProjectEconomicsReport) -> None:
    _validate_equal(
        _summaries(project.total for project in report.projects),
        report.benchmark.total,
        "all project totals",
    )
    _validate_coverage(
        report.benchmark.coverage,
        _sum_coverage(project.coverage for project in report.projects),
        "all project coverage",
    )
    _validate_metrics(
        report.benchmark.metrics,
        _sum_metrics(project.metrics for project in report.projects),
        "all project turn metrics",
    )
    for project in (report.benchmark, *report.projects):
        _validate_equal(
            _summaries(model.total for model in project.models),
            project.total,
            f"{project.key} model totals",
        )
        _validate_coverage(
            project.coverage,
            _sum_coverage(model.coverage for model in project.models),
            f"{project.key} model coverage",
        )


def _summaries(summaries: Iterable[UsageSummary]) -> UsageSummary:
    total = _empty_summary()
    for summary in summaries:
        total = total.add(summary)
    return total


def _sum_coverage(coverages: Iterable[TurnCoverage]) -> TurnCoverage:
    total_responses = measured_responses = total_tokens = measured_tokens = 0
    for coverage in coverages:
        total_responses += coverage.total_responses
        measured_responses += coverage.measured_responses
        total_tokens += coverage.total_tokens
        measured_tokens += coverage.measured_tokens
    return TurnCoverage(
        total_responses=total_responses,
        measured_responses=measured_responses,
        total_tokens=total_tokens,
        measured_tokens=measured_tokens,
    )


def _sum_metrics(metrics: Iterable[TurnMetrics]) -> TurnMetrics:
    # Median is intentionally not additive; compare it through source-level tests.
    turn_count = response_count = token_count = priced_turn_count = priced_response_count = 0
    priced_turn_cost_usd = priced_response_cost_usd = 0.0
    for metric in metrics:
        turn_count += metric.turn_count
        response_count += metric.response_count
        token_count += metric.token_count
        priced_turn_count += metric.priced_turn_count
        priced_response_count += metric.priced_response_count
        priced_turn_cost_usd += metric.priced_turn_cost_usd
        priced_response_cost_usd += metric.priced_response_cost_usd
    return TurnMetrics(
        turn_count=turn_count,
        response_count=response_count,
        token_count=token_count,
        priced_turn_count=priced_turn_count,
        priced_response_count=priced_response_count,
        priced_turn_cost_usd=priced_turn_cost_usd,
        priced_response_cost_usd=priced_response_cost_usd,
        average_cost_per_response=_ratio(priced_response_cost_usd, priced_response_count),
        average_cost_per_turn=_ratio(priced_turn_cost_usd, priced_turn_count),
        median_cost_per_turn=None,
    )


def _validate_equal(actual: UsageSummary, expected: UsageSummary, scope: str) -> None:
    for group in ("usage", "cost", "credits"):
        actual_group = getattr(actual, group)
        expected_group = getattr(expected, group)
        for field in fields(actual_group):
            actual_value = getattr(actual_group, field.name)
            expected_value = getattr(expected_group, field.name)
            if isinstance(actual_value, float):
                if not math.isclose(actual_value, expected_value, rel_tol=1e-12, abs_tol=1e-9):
                    raise ValueError(f"{scope}: {group}.{field.name} does not conserve")
            elif actual_value != expected_value:
                raise ValueError(f"{scope}: {group}.{field.name} does not conserve")
    if actual.record_count != expected.record_count:
        raise ValueError(f"{scope}: record_count does not conserve")


def _validate_coverage(actual: TurnCoverage, expected: TurnCoverage, scope: str) -> None:
    for field in fields(actual):
        if getattr(actual, field.name) != getattr(expected, field.name):
            raise ValueError(f"{scope}: {field.name} does not conserve")


def _validate_metrics(actual: TurnMetrics, expected: TurnMetrics, scope: str) -> None:
    for field_name in (
        "turn_count",
        "response_count",
        "token_count",
        "priced_turn_count",
        "priced_response_count",
    ):
        if getattr(actual, field_name) != getattr(expected, field_name):
            raise ValueError(f"{scope}: {field_name} does not conserve")
    for field_name in ("priced_turn_cost_usd", "priced_response_cost_usd"):
        if not math.isclose(
            getattr(actual, field_name), getattr(expected, field_name), rel_tol=1e-12, abs_tol=1e-9
        ):
            raise ValueError(f"{scope}: {field_name} does not conserve")
