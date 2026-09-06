from codex_usage.aggregation import AggregateRow, UsageSummary
from codex_usage.models import TokenUsage
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.report_breakdown import (
    ProjectRoleModelBreakdown,
    ReportBreakdown,
    RoleModelBreakdown,
    VisualModelBucket,
)


def row(
    key: str,
    label: str,
    total: int,
    cost: float = 0.0,
    credits: float = 0.0,
    unpriced: int = 0,
    credit_unpriced: int = 0,
    cache_write: int = 0,
) -> AggregateRow:
    return AggregateRow(
        key=key,
        label=label,
        usage=TokenUsage(
            input_tokens=total,
            cached_input_tokens=total // 2,
            cache_write_input_tokens=cache_write,
            output_tokens=10,
            total_tokens=total,
        ),
        cost=CostBreakdown(total_usd=cost, unpriced_tokens=unpriced),
        credits=CreditBreakdown(total_credits=credits, unpriced_tokens=credit_unpriced),
        record_count=1,
    )


def breakdown(
    project_rows: list[AggregateRow], model_rows: list[AggregateRow]
) -> ReportBreakdown:
    visual_models = tuple(
        VisualModelBucket(key=item.key, label=item.label, exact_models=(item.key,))
        for item in model_rows
    )
    projects = tuple(
        ProjectRoleModelBreakdown(
            row=item,
            roles=(
                RoleModelBreakdown(
                    role="root",
                    total=_summary(item),
                    model_rows=tuple(model_rows),
                ),
            ),
        )
        for item in project_rows
    )
    return ReportBreakdown(
        visual_models=visual_models,
        projects=projects,
        model_rows=tuple(model_rows),
        visual_model_rows=tuple(model_rows),
    )


def _summary(item: AggregateRow) -> UsageSummary:
    return UsageSummary(
        usage=item.usage,
        cost=item.cost,
        credits=item.credits,
        record_count=item.record_count,
    )
