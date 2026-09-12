from datetime import UTC, datetime

from codex_usage.image_models import (
    ImageEvidenceConfidence,
    ImageEvidenceSource,
    ImageModelEvidence,
    ImageOperation,
    ImageOperationKind,
    ImageOutcome,
    ImageUsage,
)
from codex_usage.image_reporting import build_image_report
from codex_usage.report_images import render_image_activity_section


def test_image_report_keeps_model_and_project_values_outside_language_totals() -> None:
    report = build_image_report(
        (
            _operation(
                "alpha",
                "Alpha",
                "gpt-image-2",
                ImageUsage(
                    text_input_tokens=100,
                    cached_text_input_tokens=0,
                    image_input_tokens=0,
                    cached_image_input_tokens=0,
                    image_output_tokens=1_000,
                    text_output_tokens=0,
                ),
                outputs=2,
            ),
            _operation("beta", "Beta", "gpt-image-2.6-orbit", ImageUsage(), outputs=1),
        )
    )

    assert report.summary.operation_count == 2
    assert report.summary.output_count == 3
    assert report.summary.api_usd.exact_operation_count == 1
    assert report.summary.api_usd.unpriced_operation_count == 1
    assert report.summary.api_usd.exact_amount == 0.0305
    assert [model.label for model in report.models] == [
        "GPT Image 2",
        "Unresolved image model",
    ]
    assert [project.label for project in report.projects] == ["Alpha", "Beta"]

    html = render_image_activity_section(report)
    assert 'data-report-section="image-activity"' in html
    assert 'aria-labelledby="image-activity-heading"' in html
    assert "Separate accounting" in html
    assert "separate from language tokens, costs, and Project Economics" in html
    assert "prompts and image contents are never retained" in html
    assert "GPT Image 2" in html and "Unresolved image model" in html
    assert "Alpha" in html and "Beta" in html
    assert "<script" not in html


def test_conflicting_image_evidence_stays_visible_but_unpriced() -> None:
    operation = _operation(
        "alpha",
        "Alpha",
        "gpt-image-2",
        ImageUsage(
            text_input_tokens=0,
            cached_text_input_tokens=0,
            image_input_tokens=0,
            cached_image_input_tokens=0,
            image_output_tokens=1,
            text_output_tokens=0,
        ),
        outputs=1,
    )
    conflicting = ImageOperation(
        **{
            field: getattr(operation, field)
            for field in operation.__dataclass_fields__
            if field != "evidence"
        },
        evidence=(
            ImageModelEvidence(
                "gpt-image-2",
                ImageEvidenceSource.RESPONSE_USAGE,
                ImageEvidenceConfidence.EXACT,
            ),
            ImageModelEvidence(
                "gpt-image-2.5-sunburst",
                ImageEvidenceSource.TOOL_INVOCATION,
                ImageEvidenceConfidence.HIGH,
            ),
        ),
    )

    report = build_image_report((conflicting,))
    assert report.summary.api_usd.unpriced_operation_count == 1
    assert report.summary.credits.unpriced_operation_count == 1


def _operation(
    project_key: str,
    project_label: str,
    model: str,
    usage: ImageUsage,
    *,
    outputs: int,
) -> ImageOperation:
    return ImageOperation(
        source_generation=1,
        tool_call_id=f"{project_key}-{model}",
        timestamp_us=int(datetime(2026, 9, 12, tzinfo=UTC).timestamp() * 1_000_000),
        task_id="task",
        root_task_id="root",
        usage_role="root",
        turn_id="turn",
        project_key=project_key,
        project_label=project_label,
        kind=ImageOperationKind.GENERATE,
        outcome=ImageOutcome.SUCCEEDED,
        output_count=outputs,
        evidence=(
            ImageModelEvidence(
                model,
                ImageEvidenceSource.RESPONSE_USAGE,
                ImageEvidenceConfidence.EXACT,
            ),
        ),
        usage=usage,
    )
