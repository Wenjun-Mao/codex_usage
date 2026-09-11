"""Independent fixture oracle for project-economics aggregation.

Keep this intentionally small and separate from ``project_economics``: it
operates on raw fixture values and has no dependency on production summary or
aggregation helpers.  It is the regression contract for the report grain.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from codex_usage.models import TokenUsage
from codex_usage.pricing import CostBreakdown, CreditBreakdown


@dataclass(frozen=True)
class RawValuedRecord:
    project: str
    task: str
    turn: str
    model: str
    role: str
    usage: TokenUsage
    cost: CostBreakdown
    credits: CreditBreakdown


@dataclass(frozen=True)
class OracleSummary:
    usage: TokenUsage
    cost: CostBreakdown
    credits: CreditBreakdown
    response_count: int


@dataclass(frozen=True)
class OracleCoverage:
    total_responses: int
    measured_responses: int
    total_tokens: int
    measured_tokens: int


@dataclass(frozen=True)
class OracleMetrics:
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


@dataclass(frozen=True)
class OracleModel:
    key: str
    total: OracleSummary
    coverage: OracleCoverage
    metrics: OracleMetrics
    token_share: float
    cost_share: float


@dataclass(frozen=True)
class OracleProject:
    key: str
    total: OracleSummary
    coverage: OracleCoverage
    metrics: OracleMetrics
    models: tuple[OracleModel, ...]


@dataclass(frozen=True)
class OracleReport:
    benchmark: OracleProject
    projects: tuple[OracleProject, ...]


def build_oracle(records: tuple[RawValuedRecord, ...]) -> OracleReport:
    """Return economics independently derived from positive raw fixture rows."""
    positive = tuple(record for record in records if record.usage.total_tokens > 0)
    project_keys = sorted(
        {record.project for record in positive},
        key=lambda key: (-sum(row.usage.total_tokens for row in positive if row.project == key), key),
    )
    projects = tuple(
        _project(key, tuple(row for row in positive if row.project == key))
        for key in project_keys
    )
    return OracleReport(benchmark=_project("__all__", positive), projects=projects)


def _project(key: str, records: tuple[RawValuedRecord, ...]) -> OracleProject:
    total = _summary(records)
    model_keys = tuple(dict.fromkeys(record.model for record in records))
    models = tuple(
        _model(model, tuple(row for row in records if row.model == model), total)
        for model in model_keys
    )
    return OracleProject(
        key=key,
        total=total,
        coverage=_coverage(records),
        metrics=_metrics(records, include_model=False),
        models=models,
    )


def _model(
    key: str, records: tuple[RawValuedRecord, ...], project_total: OracleSummary
) -> OracleModel:
    total = _summary(records)
    return OracleModel(
        key=key,
        total=total,
        coverage=_coverage(records),
        metrics=_metrics(records, include_model=True),
        token_share=_divide(total.usage.total_tokens, project_total.usage.total_tokens) or 0.0,
        cost_share=_divide(total.cost.total_usd, project_total.cost.total_usd) or 0.0,
    )


def _coverage(records: tuple[RawValuedRecord, ...]) -> OracleCoverage:
    measured = tuple(record for record in records if record.turn)
    return OracleCoverage(
        total_responses=len(records),
        measured_responses=len(measured),
        total_tokens=sum(record.usage.total_tokens for record in records),
        measured_tokens=sum(record.usage.total_tokens for record in measured),
    )


def _metrics(records: tuple[RawValuedRecord, ...], *, include_model: bool) -> OracleMetrics:
    measured = tuple(record for record in records if record.turn)
    turns: dict[tuple[str, ...], list[RawValuedRecord]] = {}
    for record in measured:
        key = (record.project, record.task, record.turn)
        if include_model:
            key += (record.model,)
        turns.setdefault(key, []).append(record)

    priced_turn_costs = [
        sum(record.cost.total_usd for record in rows)
        for rows in turns.values()
        if sum(record.cost.unpriced_tokens for record in rows) == 0
    ]
    priced_responses = tuple(
        record for record in measured if record.cost.unpriced_tokens == 0
    )
    priced_response_cost = sum(record.cost.total_usd for record in priced_responses)
    priced_turn_cost = sum(priced_turn_costs)
    return OracleMetrics(
        turn_count=len(turns),
        response_count=len(measured),
        token_count=sum(record.usage.total_tokens for record in measured),
        priced_turn_count=len(priced_turn_costs),
        priced_response_count=len(priced_responses),
        priced_turn_cost_usd=priced_turn_cost,
        priced_response_cost_usd=priced_response_cost,
        average_cost_per_response=_divide(priced_response_cost, len(priced_responses)),
        average_cost_per_turn=_divide(priced_turn_cost, len(priced_turn_costs)),
        median_cost_per_turn=median(priced_turn_costs) if priced_turn_costs else None,
    )


def _summary(records: tuple[RawValuedRecord, ...]) -> OracleSummary:
    return OracleSummary(
        usage=TokenUsage(
            input_tokens=sum(record.usage.input_tokens for record in records),
            cached_input_tokens=sum(record.usage.cached_input_tokens for record in records),
            cache_write_input_tokens=sum(record.usage.cache_write_input_tokens for record in records),
            output_tokens=sum(record.usage.output_tokens for record in records),
            reasoning_output_tokens=sum(record.usage.reasoning_output_tokens for record in records),
            total_tokens=sum(record.usage.total_tokens for record in records),
        ),
        cost=CostBreakdown(
            ordinary_input_usd=sum(record.cost.ordinary_input_usd for record in records),
            cached_input_usd=sum(record.cost.cached_input_usd for record in records),
            cache_write_input_usd=sum(record.cost.cache_write_input_usd for record in records),
            output_usd=sum(record.cost.output_usd for record in records),
            total_usd=sum(record.cost.total_usd for record in records),
            unpriced_tokens=sum(record.cost.unpriced_tokens for record in records),
        ),
        credits=CreditBreakdown(
            uncached_input_credits=sum(record.credits.uncached_input_credits for record in records),
            cached_input_credits=sum(record.credits.cached_input_credits for record in records),
            output_credits=sum(record.credits.output_credits for record in records),
            total_credits=sum(record.credits.total_credits for record in records),
            unpriced_tokens=sum(record.credits.unpriced_tokens for record in records),
        ),
        response_count=len(records),
    )


def _divide(numerator: float | int, denominator: float | int) -> float | None:
    return numerator / denominator if denominator else None
