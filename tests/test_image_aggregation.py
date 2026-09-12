from codex_usage.image_aggregation import ValuedImageOperation, summarize_image_operations
from codex_usage.image_models import ImageOperation, ImageOperationKind, ImageOutcome
from codex_usage.image_pricing import ImageMoneyRange, ImagePricingState, ImageValuation


def _operation(kind: ImageOperationKind, outcome: ImageOutcome, outputs: int) -> ImageOperation:
    return ImageOperation(
        source_generation=1,
        tool_call_id=f"call-{kind}-{outcome}",
        timestamp_us=1,
        task_id="task",
        root_task_id="root",
        usage_role="root",
        turn_id="turn",
        project_key="project",
        project_label="Project",
        kind=kind,
        outcome=outcome,
        output_count=outputs,
    )


def test_image_aggregation_keeps_exact_range_and_unpriced_coverage_separate() -> None:
    exact = ValuedImageOperation(
        _operation(ImageOperationKind.GENERATE, ImageOutcome.SUCCEEDED, 2),
        ImageValuation(
            ImageMoneyRange(ImagePricingState.EXACT, 1.0, 1.0),
            ImageMoneyRange(ImagePricingState.EXACT, 2.0, 2.0),
        ),
    )
    estimated = ValuedImageOperation(
        _operation(ImageOperationKind.EDIT_REFERENCE, ImageOutcome.SUCCEEDED, 1),
        ImageValuation(
            ImageMoneyRange(ImagePricingState.ESTIMATED_RANGE, 3.0, 5.0),
            ImageMoneyRange(ImagePricingState.UNPRICED),
        ),
    )
    unpriced = ValuedImageOperation(
        _operation(ImageOperationKind.UNKNOWN, ImageOutcome.FAILED, 0),
        ImageValuation(ImageMoneyRange(ImagePricingState.UNPRICED), ImageMoneyRange(ImagePricingState.UNPRICED)),
    )

    summary = summarize_image_operations((exact, estimated, unpriced))

    assert summary.operation_count == 3
    assert summary.output_count == 3
    assert (summary.generate_count, summary.edit_reference_count, summary.unknown_kind_count) == (1, 1, 1)
    assert (summary.succeeded_count, summary.failed_count) == (2, 1)
    assert summary.api_usd.exact_amount == 1.0
    assert (summary.api_usd.estimated_low, summary.api_usd.estimated_high) == (3.0, 5.0)
    assert summary.api_usd.unpriced_operation_count == 1
    assert summary.credits.exact_amount == 2.0
    assert summary.credits.unpriced_operation_count == 2
