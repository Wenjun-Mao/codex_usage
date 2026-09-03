from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


PLATFORMS = {
    "darwin-aarch64": "Codex-Usage-{version}-darwin-aarch64.app.tar.gz",
    "windows-x86_64": "Codex-Usage-{version}-windows-x86_64.nsis.zip",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create signed Tauri update metadata and release checksums."
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--published-at")
    args = parser.parse_args()

    version = args.version.removeprefix("v")
    tag = f"v{version}"
    directory = args.directory.resolve()
    platforms: dict[str, dict[str, str]] = {}
    for platform, pattern in PLATFORMS.items():
        artifact = directory / pattern.format(version=version)
        signature = artifact.with_name(f"{artifact.name}.sig")
        if not artifact.is_file() or not signature.is_file():
            raise FileNotFoundError(f"missing updater artifact or signature: {artifact}")
        encoded_signature = signature.read_text(encoding="utf-8").strip()
        if not encoded_signature:
            raise ValueError(f"empty updater signature: {signature}")
        platforms[platform] = {
            "signature": encoded_signature,
            "url": (
                f"https://github.com/{args.repository}/releases/download/"
                f"{tag}/{artifact.name}"
            ),
        }

    published_at = args.published_at or datetime.now(UTC).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    latest = {
        "version": version,
        "notes": f"Codex Usage {version}",
        "pub_date": published_at,
        "platforms": platforms,
    }
    latest_path = directory / "latest.json"
    latest_path.write_text(
        json.dumps(latest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    checksum_targets = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    checksums = "".join(
        f"{_sha256(path)}  {path.name}\n" for path in checksum_targets
    )
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
