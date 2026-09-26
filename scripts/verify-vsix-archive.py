"""Audit the produced VSIX rather than only the files offered to vsce."""

import argparse
from pathlib import Path
from zipfile import ZipFile

AGENTS = {
    "darwin-arm64": "extension/bin/darwin-arm64/codex-usage-agent",
    "win32-x64": "extension/bin/win32-x64/codex-usage-agent.exe",
}
REQUIRED = {"extension/package.json", "extension/out/extension.js"}


def verify_archive(archive: Path, target: str) -> None:
    with ZipFile(archive) as package:
        files = set(package.namelist())
    expected_agent = AGENTS[target]
    collectors = {
        name
        for name in files
        if name.startswith("extension/bin/") and not name.endswith("/")
    }
    missing = (REQUIRED | {expected_agent}) - files
    unexpected = collectors - {expected_agent}
    native_files = {name for name in files if "src-tauri/" in name or name.startswith("extension/apps/desktop/")}
    if missing or unexpected or native_files or len(collectors) != 1:
        raise ValueError(
            f"Invalid {target} VSIX: missing={sorted(missing)}, "
            f"collectors={sorted(collectors)}, native_files={sorted(native_files)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("target", choices=AGENTS)
    args = parser.parse_args()
    verify_archive(args.archive, args.target)
    print(f"Verified {args.target} VSIX: {args.archive}")


if __name__ == "__main__":
    main()
