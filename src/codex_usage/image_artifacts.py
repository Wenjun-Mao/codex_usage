"""Bounded metadata inspection for generated-image artifacts.

Only the PNG header and a small provenance prefix are read.  Image pixels,
paths, prompts, and embedded payloads never enter the accounting records.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import struct

from codex_usage.image_models import (
    ImageEvidenceConfidence,
    ImageEvidenceSource,
    ImageModelEvidence,
)


MAX_ARTIFACT_METADATA_BYTES = 256 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SAFE_ARTIFACT_NAME = re.compile(
    r"^exec-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.png$",
    re.IGNORECASE,
)
_SIGNED_AGENT = re.compile(
    rb"softwareAgent.{0,96}gpt-image.{0,48}version.{0,16}(2\.5|2\.0)",
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class ImageArtifactMetadata:
    width: int | None = None
    height: int | None = None
    output_format: str = ""
    evidence: tuple[ImageModelEvidence, ...] = ()


def inspect_generated_artifact(
    artifact_directory: Path | None,
    basename: str,
) -> ImageArtifactMetadata:
    """Inspect one exact generated artifact without following arbitrary paths."""
    if artifact_directory is None or not _SAFE_ARTIFACT_NAME.fullmatch(basename):
        return ImageArtifactMetadata()
    path = artifact_directory / basename
    try:
        with path.open("rb") as handle:
            prefix = handle.read(MAX_ARTIFACT_METADATA_BYTES)
    except OSError:
        return ImageArtifactMetadata()
    if len(prefix) < 24 or not prefix.startswith(_PNG_SIGNATURE):
        return ImageArtifactMetadata()
    width, height = struct.unpack(">II", prefix[16:24])
    evidence: tuple[ImageModelEvidence, ...] = ()
    if all(marker in prefix for marker in (b"c2pa.actions.v2", b"c2pa.signature")):
        match = _SIGNED_AGENT.search(prefix)
        if match is not None:
            evidence = (
                ImageModelEvidence(
                    "gpt-image",
                    ImageEvidenceSource.SIGNED_C2PA,
                    ImageEvidenceConfidence.HIGH,
                    match.group(1).decode("ascii"),
                ),
            )
    return ImageArtifactMetadata(width, height, "png", evidence)
