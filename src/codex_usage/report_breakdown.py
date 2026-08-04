from __future__ import annotations

import math
from dataclasses import dataclass, fields

from codex_usage.aggregation import AggregateRow, UsageSummary, summarize_record
from codex_usage.models import (
    ROOT_USAGE_ROLE,
    SUBAGENT_USAGE_ROLE,
    TokenUsage,
    UsageRecord,
    UsageRole,
)
from codex_usage.pricing import CostBreakdown, CreditBreakdown

OTHER_MODEL_KEY = "__codex_usage_other_models__"
OTHER_MODEL_LABEL = "Other"
MAX_VISUAL_MODEL_COUNT = 7
_ROLE_ORDER: tuple[UsageRole, ...] = (ROOT_USAGE_ROLE, SUBAGENT_USAGE_ROLE)


@dataclass(frozen=True, slots=True)
class VisualModelBucket:
    key: str
    label: str
    exact_models: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoleModelBreakdown:
    role: UsageRole
    total: UsageSummary
    model_rows: tuple[AggregateRow, ...]


@dataclass(frozen=True, slots=True)
class ProjectRoleModelBreakdown:
    row: AggregateRow
    roles: tuple[RoleModelBreakdown, ...]


@dataclass(frozen=True, slots=True)
class ReportBreakdown:
    visual_models: tuple[VisualModelBucket, ...]
    projects: tuple[ProjectRoleModelBreakdown, ...]
    model_rows: tuple[AggregateRow, ...]
    visual_model_rows: tuple[AggregateRow, ...]

    @property
    def project_rows(self) -> tuple[AggregateRow, ...]:
        return tuple(project.row for project in self.projects)


def build_report_breakdown(
    records: list[UsageRecord],
    *,
    visual_model_limit: int = 7,
) -> ReportBreakdown:
    if not 0 <= visual_model_limit <= MAX_VISUAL_MODEL_COUNT:
        raise ValueError(
            f"visual_model_limit must be between 0 and {MAX_VISUAL_MODEL_COUNT}"
        )

    project_role_model: dict[str, dict[UsageRole, dict[str, UsageSummary]]] = {}
    project_totals: dict[str, UsageSummary] = {}
    project_labels: dict[str, str] = {}
    model_totals: dict[str, UsageSummary] = {}

    for record in records:
        if record.usage.total_tokens <= 0:
            continue
        record_summary = summarize_record(record)
        project_labels[record.project_key] = record.project_label
        project_totals[record.project_key] = _add(
            project_totals.get(record.project_key), record_summary
        )
        model_totals[record.model] = _add(model_totals.get(record.model), record_summary)
        role_models = project_role_model.setdefault(record.project_key, {}).setdefault(
            record.usage_role, {}
        )
        role_models[record.model] = _add(role_models.get(record.model), record_summary)

    visual_models = _visual_models(model_totals, visual_model_limit)
    model_rows = tuple(
        _row(model, model, summary)
        for model, summary in sorted(
            model_totals.items(), key=lambda item: (-item[1].usage.total_tokens, item[0])
        )
        if summary.usage.total_tokens > 0
    )
    visual_model_rows = tuple(
        _row(bucket.key, bucket.label, summary)
        for bucket in visual_models
        if (summary := _models_summary(model_totals, bucket.exact_models)) is not None
        and summary.usage.total_tokens > 0
    )
    projects = tuple(
        _project_breakdown(
            project_key,
            project_labels[project_key],
            project_totals[project_key],
            project_role_model[project_key],
            visual_models,
        )
        for project_key in sorted(
            project_totals,
            key=lambda key: (-project_totals[key].usage.total_tokens, key),
        )
        if project_totals[project_key].usage.total_tokens > 0
    )
    report = ReportBreakdown(
        visual_models=visual_models,
        projects=projects,
        model_rows=model_rows,
        visual_model_rows=visual_model_rows,
    )
    _validate_breakdown(report)
    return report


def _add(summary: UsageSummary | None, value: UsageSummary) -> UsageSummary:
    return value if summary is None else summary.add(value)


def _visual_models(
    model_totals: dict[str, UsageSummary], visual_model_limit: int
) -> tuple[VisualModelBucket, ...]:
    ranked_models = sorted(
        model_totals,
        key=lambda model: (-model_totals[model].usage.total_tokens, model),
    )
    exact_models = ranked_models[:visual_model_limit]
    buckets = [
        VisualModelBucket(key=model, label=model, exact_models=(model,))
        for model in exact_models
    ]
    other_models = ranked_models[visual_model_limit:]
    if other_models:
        buckets.append(
            VisualModelBucket(
                key=OTHER_MODEL_KEY,
                label=OTHER_MODEL_LABEL,
                exact_models=tuple(sorted(other_models)),
            )
        )
    return tuple(buckets)


def _project_breakdown(
    project_key: str,
    project_label: str,
    project_total: UsageSummary,
    role_models: dict[UsageRole, dict[str, UsageSummary]],
    visual_models: tuple[VisualModelBucket, ...],
) -> ProjectRoleModelBreakdown:
    roles = tuple(
        RoleModelBreakdown(
            role=role,
            total=_models_summary(role_models[role], tuple(role_models[role])) or _empty_summary(),
            model_rows=tuple(
                _row(bucket.key, bucket.label, summary)
                for bucket in visual_models
                if (
                    summary := _models_summary(role_models[role], bucket.exact_models)
                ) is not None
                and summary.usage.total_tokens > 0
            ),
        )
        for role in _ROLE_ORDER
        if role in role_models
    )
    return ProjectRoleModelBreakdown(
        row=_row(project_key, project_label, project_total),
        roles=roles,
    )


def _models_summary(
    summaries: dict[str, UsageSummary], models: tuple[str, ...]
) -> UsageSummary | None:
    total: UsageSummary | None = None
    for model in models:
        if (summary := summaries.get(model)) is not None:
            total = _add(total, summary)
    return total


def _empty_summary() -> UsageSummary:
    return UsageSummary(
        usage=TokenUsage(),
        cost=CostBreakdown(),
        credits=CreditBreakdown(),
        record_count=0,
    )


def _row(key: str, label: str, summary: UsageSummary) -> AggregateRow:
    return AggregateRow(
        key=key,
        label=label,
        usage=summary.usage,
        cost=summary.cost,
        credits=summary.credits,
        record_count=summary.record_count,
    )


def _validate_breakdown(report: ReportBreakdown) -> None:
    for project in report.projects:
        _validate_equal(
            _rows_summary(tuple(role.total for role in project.roles)),
            _summary_from_row(project.row),
            f"project {project.row.key} roles",
        )
        for role in project.roles:
            _validate_equal(
                _rows_summary(role.model_rows),
                role.total,
                f"project {project.row.key} role {role.role} models",
            )
    _validate_equal(
        _rows_summary(report.model_rows),
        _rows_summary(report.visual_model_rows),
        "global model rows",
    )
    _validate_equal(
        _rows_summary(tuple(project.row for project in report.projects)),
        _rows_summary(report.model_rows),
        "global project rows",
    )


def _rows_summary(rows: tuple[AggregateRow | UsageSummary, ...]) -> UsageSummary:
    total = _empty_summary()
    for row in rows:
        summary = row if isinstance(row, UsageSummary) else _summary_from_row(row)
        total = total.add(summary)
    return total


def _summary_from_row(row: AggregateRow) -> UsageSummary:
    return UsageSummary(
        usage=row.usage,
        cost=row.cost,
        credits=row.credits,
        record_count=row.record_count,
    )


def _validate_equal(actual: UsageSummary, expected: UsageSummary, scope: str) -> None:
    for group in ("usage", "cost", "credits"):
        actual_group = getattr(actual, group)
        expected_group = getattr(expected, group)
        for field in fields(actual_group):
            actual_value = getattr(actual_group, field.name)
            expected_value = getattr(expected_group, field.name)
            if isinstance(actual_value, float):
                if not math.isclose(actual_value, expected_value, rel_tol=0.0, abs_tol=1e-9):
                    raise ValueError(f"{scope}: {group}.{field.name} does not conserve")
            elif actual_value != expected_value:
                raise ValueError(f"{scope}: {group}.{field.name} does not conserve")
    if actual.record_count != expected.record_count:
        raise ValueError(f"{scope}: record_count does not conserve")
