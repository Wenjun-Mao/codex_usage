from codex_usage.image_models import (
    ImageEvidenceConfidence,
    ImageEvidenceSource,
    ImageModelEvidence,
    ImageModelFamily,
    ImageModelVariant,
    ImageOperation,
    ImageOperationKind,
    ImageOutcome,
    normalize_image_model,
    resolve_image_model_evidence,
)


def test_normalizes_documented_api_models_and_snapshots() -> None:
    image_2 = normalize_image_model("gpt-image-2-2026-04-21")
    sunburst = normalize_image_model("GPT-IMAGE-2.5-SUNBURST-2026-09-08")
    flare = normalize_image_model("gpt-image-2.5-flare")

    assert image_2.family is ImageModelFamily.GPT_IMAGE_2
    assert image_2.variant is ImageModelVariant.UNKNOWN
    assert sunburst.family is ImageModelFamily.GPT_IMAGE_2_5
    assert sunburst.variant is ImageModelVariant.SUNBURST
    assert flare.variant is ImageModelVariant.FLARE


def test_signed_versions_identify_a_family_without_inventing_a_2_5_variant() -> None:
    image_2 = normalize_image_model("gpt-image", version="2.0")
    image_2_5 = normalize_image_model("gpt-image", version="2.5")

    assert image_2.family is ImageModelFamily.GPT_IMAGE_2
    assert image_2_5.family is ImageModelFamily.GPT_IMAGE_2_5
    assert image_2_5.variant is ImageModelVariant.UNKNOWN


def test_unknown_future_gpt_image_identity_remains_visible_but_unpriced() -> None:
    future = normalize_image_model("gpt-image-2.6-orbit")

    assert future.recognized_image_activity is True
    assert future.family is ImageModelFamily.UNKNOWN
    assert future.pricing_key is None


def test_response_usage_wins_over_tool_and_signed_metadata_and_keeps_conflict() -> None:
    signed = ImageModelEvidence(
        "gpt-image",
        ImageEvidenceSource.SIGNED_C2PA,
        ImageEvidenceConfidence.HIGH,
        version="2.0",
    )
    tool = ImageModelEvidence(
        "gpt-image-2.5-sunburst",
        ImageEvidenceSource.TOOL_INVOCATION,
        ImageEvidenceConfidence.HIGH,
    )
    response = ImageModelEvidence(
        "gpt-image-2.5-flare",
        ImageEvidenceSource.RESPONSE_USAGE,
        ImageEvidenceConfidence.EXACT,
    )

    resolved = resolve_image_model_evidence((signed, tool, response))

    assert resolved.selected == response
    assert resolved.model.variant is ImageModelVariant.FLARE
    assert resolved.has_conflict is True
    assert resolved.all_evidence == (signed, tool, response)


def test_family_only_signed_2_5_evidence_is_compatible_with_a_named_variant() -> None:
    signed = ImageModelEvidence(
        "gpt-image",
        ImageEvidenceSource.SIGNED_C2PA,
        ImageEvidenceConfidence.HIGH,
        version="2.5",
    )
    response = ImageModelEvidence(
        "gpt-image-2.5-sunburst",
        ImageEvidenceSource.RESPONSE_USAGE,
        ImageEvidenceConfidence.EXACT,
    )

    resolved = resolve_image_model_evidence((signed, response))

    assert resolved.model.variant is ImageModelVariant.SUNBURST
    assert resolved.has_conflict is False


def test_operation_identity_uses_source_generation_and_call_id_not_output_count() -> None:
    operation = ImageOperation(
        source_generation=12,
        tool_call_id="call-7",
        timestamp_us=1,
        task_id="task",
        root_task_id="root",
        usage_role="root",
        turn_id="turn",
        project_key="project",
        project_label="Project",
        kind=ImageOperationKind.EDIT_REFERENCE,
        outcome=ImageOutcome.SUCCEEDED,
        output_count=3,
    )

    assert operation.operation_key == (12, "call-7")
    assert operation.output_count == 3
