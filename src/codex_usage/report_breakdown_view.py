from __future__ import annotations

from dataclasses import dataclass

from codex_usage.aggregation import AggregateRow
from codex_usage.models import TokenUsage, UsageRole
from codex_usage.model_presentation import assign_model_color_slots
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.report_breakdown import (
    OTHER_MODEL_KEY,
    ReportBreakdown,
    RoleModelBreakdown,
)

_ROLE_LABELS: dict[UsageRole, str] = {
    "root": "Root tasks",
    "subagent": "Subagents",
}


@dataclass(frozen=True, slots=True)
class ModelLegendItem:
    key: str
    label: str
    color_slot: int


@dataclass(frozen=True, slots=True)
class ModelSegmentPoint:
    key: str
    label: str
    color_slot: int
    total_tokens: int
    cost_usd: float
    total_credits: float
    unpriced_tokens: int
    credit_unpriced_tokens: int
    record_count: int
    project_share: float
    project_cost_share: float


@dataclass(frozen=True, slots=True)
class RoleGroupPoint:
    role: UsageRole
    label: str
    total_tokens: int
    cost_usd: float
    project_share: float
    project_cost_share: float
    segments: tuple[ModelSegmentPoint, ...]


@dataclass(frozen=True, slots=True)
class ProjectBreakdownPoint:
    key: str
    label: str
    usage: TokenUsage
    cost: CostBreakdown
    credits: CreditBreakdown
    record_count: int
    root_tokens: int
    subagent_tokens: int
    root_cost_usd: float
    subagent_cost_usd: float
    roles: tuple[RoleGroupPoint, ...]

    @property
    def total_tokens(self) -> int:
        return self.usage.total_tokens

    @property
    def cost_usd(self) -> float:
        return self.cost.total_usd

    @property
    def total_credits(self) -> float:
        return self.credits.total_credits

    @property
    def unpriced_tokens(self) -> int:
        return self.cost.unpriced_tokens

    @property
    def credit_unpriced_tokens(self) -> int:
        return self.credits.unpriced_tokens


@dataclass(frozen=True, slots=True)
class ModelMixPoint:
    key: str
    label: str
    color_slot: int
    total_tokens: int
    cost_usd: float
    total_credits: float
    unpriced_tokens: int
    credit_unpriced_tokens: int
    record_count: int


@dataclass(frozen=True, slots=True)
class BreakdownView:
    model_legend: tuple[ModelLegendItem, ...]
    project_points: tuple[ProjectBreakdownPoint, ...]
    model_points: tuple[ModelMixPoint, ...]


def build_breakdown_view(breakdown: ReportBreakdown) -> BreakdownView:
    exact_model_keys = tuple(
        bucket.key for bucket in breakdown.visual_models if bucket.key != OTHER_MODEL_KEY
    )
    color_slots = assign_model_color_slots(exact_model_keys)
    if any(bucket.key == OTHER_MODEL_KEY for bucket in breakdown.visual_models):
        color_slots[OTHER_MODEL_KEY] = 7
    model_legend = tuple(
        ModelLegendItem(
            key=bucket.key,
            label=bucket.label,
            color_slot=color_slots[bucket.key],
        )
        for bucket in breakdown.visual_models
    )
    project_points = tuple(
        _project_point(project.row, project.roles, color_slots)
        for project in breakdown.projects
    )
    model_points = tuple(
        _model_point(row, color_slots[row.key])
        for row in breakdown.visual_model_rows
    )
    return BreakdownView(
        model_legend=model_legend,
        project_points=project_points,
        model_points=model_points,
    )


def _project_point(
    row: AggregateRow,
    roles: tuple[RoleModelBreakdown, ...],
    color_slots: dict[str, int],
) -> ProjectBreakdownPoint:
    total_tokens = row.usage.total_tokens
    total_cost_usd = row.cost.total_usd
    role_points = tuple(
        _role_point(role, total_tokens, total_cost_usd, color_slots) for role in roles
    )
    role_totals = {role.role: role.total.usage.total_tokens for role in roles}
    role_costs = {role.role: role.total.cost.total_usd for role in roles}
    return ProjectBreakdownPoint(
        key=row.key,
        label=row.label,
        usage=row.usage,
        cost=row.cost,
        credits=row.credits,
        record_count=row.record_count,
        root_tokens=role_totals.get("root", 0),
        subagent_tokens=role_totals.get("subagent", 0),
        root_cost_usd=role_costs.get("root", 0.0),
        subagent_cost_usd=role_costs.get("subagent", 0.0),
        roles=role_points,
    )


def _role_point(
    role: RoleModelBreakdown,
    project_total_tokens: int,
    project_total_cost_usd: float,
    color_slots: dict[str, int],
) -> RoleGroupPoint:
    total_tokens = role.total.usage.total_tokens
    cost_usd = role.total.cost.total_usd
    return RoleGroupPoint(
        role=role.role,
        label=_ROLE_LABELS[role.role],
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        project_share=_share(total_tokens, project_total_tokens),
        project_cost_share=_share(cost_usd, project_total_cost_usd),
        segments=tuple(
            _segment_point(
                row,
                color_slots[row.key],
                project_total_tokens,
                project_total_cost_usd,
            )
            for row in role.model_rows
        ),
    )


def _segment_point(
    row: AggregateRow,
    color_slot: int,
    project_total_tokens: int,
    project_total_cost_usd: float,
) -> ModelSegmentPoint:
    return ModelSegmentPoint(
        key=row.key,
        label=row.label,
        color_slot=color_slot,
        total_tokens=row.usage.total_tokens,
        cost_usd=row.cost.total_usd,
        total_credits=row.credits.total_credits,
        unpriced_tokens=row.cost.unpriced_tokens,
        credit_unpriced_tokens=row.credits.unpriced_tokens,
        record_count=row.record_count,
        project_share=_share(row.usage.total_tokens, project_total_tokens),
        project_cost_share=_share(row.cost.total_usd, project_total_cost_usd),
    )


def _model_point(row: AggregateRow, color_slot: int) -> ModelMixPoint:
    return ModelMixPoint(
        key=row.key,
        label=row.label,
        color_slot=color_slot,
        total_tokens=row.usage.total_tokens,
        cost_usd=row.cost.total_usd,
        total_credits=row.credits.total_credits,
        unpriced_tokens=row.cost.unpriced_tokens,
        credit_unpriced_tokens=row.credits.unpriced_tokens,
        record_count=row.record_count,
    )


def _share(value: int | float, total: int | float) -> float:
    return value / total if total else 0.0
