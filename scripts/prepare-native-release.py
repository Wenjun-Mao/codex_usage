from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


PREVIEW_ARTIFACTS = {
    "darwin-aarch64": "Codex-Usage-{version}-macos-arm64-unsigned-preview.dmg",
    "windows-x86_64": "Codex-Usage-{version}-windows-x64-unsigned-preview-setup.exe",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create integrity metadata for one unsigned native preview artifact."
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", choices=sorted(PREVIEW_ARTIFACTS), required=True)
    args = parser.parse_args()

    version = args.version.removeprefix("v")
    directory = args.directory.resolve()
    artifact = directory / PREVIEW_ARTIFACTS[args.platform].format(version=version)
    if not artifact.is_file():
        raise FileNotFoundError(f"missing unsigned preview artifact: {artifact}")

    generated_at = datetime.now(UTC).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    integrity = {
        "schema_version": 1,
        "kind": "codex-usage-unsigned-preview-integrity",
        "version": version,
        "platform": args.platform,
        "generated_at": generated_at,
        "artifact": {
            "name": artifact.name,
            "sha256": _sha256(artifact),
        },
    }
    integrity_path = directory / "preview-integrity.json"
    integrity_path.write_text(
        json.dumps(integrity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checksums = f"{integrity['artifact']['sha256']}  {artifact.name}\n"
    (directory / "SHA256SUMS.txt").write_text(checksums, encoding="ascii")
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
