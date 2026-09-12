"""Privacy-preserving domain contracts for Codex image-generation activity.

The image ledger deliberately has no prompt, file path, byte payload, or image
content fields.  It records only the minimum identity, attribution, model
evidence, and usage metadata needed to report an independently priced activity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


class ImageOperationKind(StrEnum):
    GENERATE = "generate"
    EDIT_REFERENCE = "edit_reference"
    UNKNOWN = "unknown"


class ImageOutcome(StrEnum):
    ATTEMPTED = "attempted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ImageModelFamily(StrEnum):
    GPT_IMAGE_2 = "gpt-image-2"
    GPT_IMAGE_2_5 = "gpt-image-2.5"
    UNKNOWN = "unknown"


class ImageModelVariant(StrEnum):
    SUNBURST = "sunburst"
    FLARE = "flare"
    UNKNOWN = "unknown"


class ImageEvidenceSource(StrEnum):
    RESPONSE_USAGE = "response_usage"
    TOOL_INVOCATION = "tool_invocation"
    SIGNED_C2PA = "signed_c2pa"
    ACTIVITY_INFERENCE = "activity_inference"


class ImageEvidenceConfidence(StrEnum):
    EXACT = "exact"
    HIGH = "high"
    LOW = "low"


_EVIDENCE_PRECEDENCE = {
    ImageEvidenceSource.RESPONSE_USAGE: 4,
    ImageEvidenceSource.TOOL_INVOCATION: 3,
    ImageEvidenceSource.SIGNED_C2PA: 2,
    ImageEvidenceSource.ACTIVITY_INFERENCE: 1,
}
_CONFIDENCE_PRECEDENCE = {
    ImageEvidenceConfidence.EXACT: 3,
    ImageEvidenceConfidence.HIGH: 2,
    ImageEvidenceConfidence.LOW: 1,
}
_API_MODEL = re.compile(
    r"^(?P<family>gpt-image-2(?:\.5)?)(?:-(?P<variant>sunburst|flare))?(?:-\d{4}-\d{2}-\d{2})?$",
    re.IGNORECASE,
)
_FUTURE_GPT_IMAGE_2 = re.compile(r"^gpt-image-2\.\d+(?:-[a-z0-9-]+)?$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ImageModelEvidence:
    """One retained model observation, never a filename-derived guess."""

    raw_identity: str
    source: ImageEvidenceSource
    confidence: ImageEvidenceConfidence
    version: str = ""

    @property
    def normalized(self) -> "NormalizedImageModel":
        return normalize_image_model(self.raw_identity, version=self.version)


@dataclass(frozen=True, slots=True)
class NormalizedImageModel:
    family: ImageModelFamily
    variant: ImageModelVariant
    raw_identity: str
    recognized_image_activity: bool

    @property
    def pricing_key(self) -> str | None:
        if self.family is ImageModelFamily.GPT_IMAGE_2:
            return self.family.value
        if self.family is ImageModelFamily.GPT_IMAGE_2_5:
            return self.family.value
        return None


@dataclass(frozen=True, slots=True)
class ResolvedImageModelEvidence:
    """The selected evidence plus all retained evidence for later audit."""

    selected: ImageModelEvidence | None
    all_evidence: tuple[ImageModelEvidence, ...]
    has_conflict: bool

    @property
    def model(self) -> NormalizedImageModel:
        if self.selected is None:
            return NormalizedImageModel(
                family=ImageModelFamily.UNKNOWN,
                variant=ImageModelVariant.UNKNOWN,
                raw_identity="",
                recognized_image_activity=True,
            )
        return self.selected.normalized


@dataclass(frozen=True, slots=True)
class ImageUsage:
    """Upstream image usage fields, intentionally distinct from TokenUsage.

    ``None`` means absent upstream telemetry, while zero is an observed zero.
    Exact valuation requires every billable input/output category to be present.
    """

    text_input_tokens: int | None = None
    cached_text_input_tokens: int | None = None
    text_output_tokens: int | None = None
    image_input_tokens: int | None = None
    cached_image_input_tokens: int | None = None
    image_output_tokens: int | None = None
    total_tokens: int | None = None

    @property
    def has_complete_api_usage(self) -> bool:
        return all(
            value is not None
            for value in (
                self.text_input_tokens,
                self.cached_text_input_tokens,
                self.image_input_tokens,
                self.cached_image_input_tokens,
                self.image_output_tokens,
            )
        )

    @property
    def has_complete_credit_usage(self) -> bool:
        return self.has_complete_api_usage and self.text_output_tokens is not None


@dataclass(frozen=True, slots=True)
class ImageOperation:
    """A single tool-call identity.  Output count is deliberately separate."""

    source_generation: int
    tool_call_id: str
    timestamp_us: int
    task_id: str
    root_task_id: str
    usage_role: str
    turn_id: str
    project_key: str
    project_label: str
    kind: ImageOperationKind
    outcome: ImageOutcome
    output_count: int = 0
    output_width: int | None = None
    output_height: int | None = None
    output_format: str = ""
    quality: str = ""
    evidence: tuple[ImageModelEvidence, ...] = ()
    usage: ImageUsage = ImageUsage()

    @property
    def operation_key(self) -> tuple[int, str]:
        return (self.source_generation, self.tool_call_id)


def normalize_image_model(raw_identity: str, *, version: str = "") -> NormalizedImageModel:
    """Normalize only documented identities; unknown future families stay visible."""
    raw = raw_identity.strip()
    normalized = raw.casefold()
    signed_version = version.strip().casefold()

    if normalized == "gpt-image" and signed_version in {"2.0", "2"}:
        return _known_model(ImageModelFamily.GPT_IMAGE_2, raw)
    if normalized == "gpt-image" and signed_version == "2.5":
        return _known_model(ImageModelFamily.GPT_IMAGE_2_5, raw)

    match = _API_MODEL.fullmatch(normalized)
    if match is not None:
        family = ImageModelFamily(match.group("family").casefold())
        variant_text = match.group("variant")
        variant = ImageModelVariant(variant_text) if variant_text else ImageModelVariant.UNKNOWN
        return NormalizedImageModel(family, variant, raw, True)

    return NormalizedImageModel(
        family=ImageModelFamily.UNKNOWN,
        variant=ImageModelVariant.UNKNOWN,
        raw_identity=raw,
        recognized_image_activity=bool(_FUTURE_GPT_IMAGE_2.fullmatch(normalized)),
    )


def resolve_image_model_evidence(
    evidence: tuple[ImageModelEvidence, ...],
) -> ResolvedImageModelEvidence:
    """Apply source precedence without discarding contradictory raw evidence."""
    if not evidence:
        return ResolvedImageModelEvidence(None, (), False)

    selected = max(
        evidence,
        key=lambda item: (
            _EVIDENCE_PRECEDENCE[item.source],
            _CONFIDENCE_PRECEDENCE[item.confidence],
        ),
    )
    selected_model = selected.normalized
    known_models = [item.normalized for item in evidence if item.normalized.pricing_key is not None]
    known_families = {item.family for item in known_models}
    known_2_5_variants = {
        item.variant
        for item in known_models
        if item.family is ImageModelFamily.GPT_IMAGE_2_5 and item.variant is not ImageModelVariant.UNKNOWN
    }
    return ResolvedImageModelEvidence(
        selected=selected,
        all_evidence=evidence,
        has_conflict=(len(known_families) > 1 or len(known_2_5_variants) > 1)
        and selected_model.pricing_key is not None,
    )


def _known_model(family: ImageModelFamily, raw_identity: str) -> NormalizedImageModel:
    return NormalizedImageModel(
        family=family,
        variant=ImageModelVariant.UNKNOWN,
        raw_identity=raw_identity,
        recognized_image_activity=True,
    )
