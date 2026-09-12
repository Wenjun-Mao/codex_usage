"""Additive image activity aggregation that never feeds language economics."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from codex_usage.image_models import ImageOperation, ImageOperationKind, ImageOutcome
from codex_usage.image_pricing import ImageMoneyRange, ImagePricingState, ImageValuation


@dataclass(frozen=True, slots=True)
class ImageValueCoverage:
    exact_amount: float = 0.0
    estimated_low: float = 0.0
    estimated_high: float = 0.0
    exact_operation_count: int = 0
    estimated_operation_count: int = 0
    unpriced_operation_count: int = 0
    credit_equivalent_operation_count: int = 0

    def add(self, value: ImageMoneyRange) -> "ImageValueCoverage":
        if value.state is ImagePricingState.EXACT:
            assert value.low is not None
            return ImageValueCoverage(
                exact_amount=self.exact_amount + value.low,
                estimated_low=self.estimated_low,
                estimated_high=self.estimated_high,
                exact_operation_count=self.exact_operation_count + 1,
                estimated_operation_count=self.estimated_operation_count,
                unpriced_operation_count=self.unpriced_operation_count,
                credit_equivalent_operation_count=(
                    self.credit_equivalent_operation_count + int(value.credit_equivalent)
                ),
            )
        if value.state is ImagePricingState.ESTIMATED_RANGE:
            assert value.low is not None and value.high is not None
            return ImageValueCoverage(
                exact_amount=self.exact_amount,
                estimated_low=self.estimated_low + value.low,
                estimated_high=self.estimated_high + value.high,
                exact_operation_count=self.exact_operation_count,
                estimated_operation_count=self.estimated_operation_count + 1,
                unpriced_operation_count=self.unpriced_operation_count,
                credit_equivalent_operation_count=(
                    self.credit_equivalent_operation_count + int(value.credit_equivalent)
                ),
            )
        return ImageValueCoverage(
            exact_amount=self.exact_amount,
            estimated_low=self.estimated_low,
            estimated_high=self.estimated_high,
            exact_operation_count=self.exact_operation_count,
            estimated_operation_count=self.estimated_operation_count,
            unpriced_operation_count=self.unpriced_operation_count + 1,
            credit_equivalent_operation_count=self.credit_equivalent_operation_count,
        )


@dataclass(frozen=True, slots=True)
class ValuedImageOperation:
    operation: ImageOperation
    valuation: ImageValuation


@dataclass(frozen=True, slots=True)
class ImageActivitySummary:
    operation_count: int = 0
    output_count: int = 0
    generate_count: int = 0
    edit_reference_count: int = 0
    unknown_kind_count: int = 0
    attempted_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    api_usd: ImageValueCoverage = field(default_factory=ImageValueCoverage)
    credits: ImageValueCoverage = field(default_factory=ImageValueCoverage)

    def add(self, valued: ValuedImageOperation) -> "ImageActivitySummary":
        operation = valued.operation
        return ImageActivitySummary(
            operation_count=self.operation_count + 1,
            output_count=self.output_count + operation.output_count,
            generate_count=self.generate_count + int(operation.kind is ImageOperationKind.GENERATE),
            edit_reference_count=self.edit_reference_count + int(operation.kind is ImageOperationKind.EDIT_REFERENCE),
            unknown_kind_count=self.unknown_kind_count + int(operation.kind is ImageOperationKind.UNKNOWN),
            attempted_count=self.attempted_count + int(operation.outcome is ImageOutcome.ATTEMPTED),
            succeeded_count=self.succeeded_count + int(operation.outcome is ImageOutcome.SUCCEEDED),
            failed_count=self.failed_count + int(operation.outcome is ImageOutcome.FAILED),
            api_usd=self.api_usd.add(valued.valuation.api_usd),
            credits=self.credits.add(valued.valuation.credits),
        )


def summarize_image_operations(
    operations: Iterable[ValuedImageOperation],
) -> ImageActivitySummary:
    summary = ImageActivitySummary()
    for operation in operations:
        summary = summary.add(operation)
    return summary
