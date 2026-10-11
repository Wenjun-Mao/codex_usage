"""Bind the retained source candidate and optional built collector, without launch."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--verify-source", type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    paths = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
        "--", "src", "extensions/vscode/src", "extensions/vscode/test", "extensions/vscode/package.json",
        "extensions/vscode/package-lock.json", "pyproject.toml", "uv.lock", "scripts", "tests", "docs/adr/0054-usage-allowance-breakdown.md",
        "docs/plans/usage-burn-breakdown.md"], cwd=repo).decode().split("\0")
    files = {p: hashlib.sha256((repo/p).read_bytes()).hexdigest() for p in sorted(set(paths)) if p and (repo/p).is_file()}
    source = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if args.verify_source:
        assert source == json.loads(args.verify_source.read_text())["source_sha256"], "Source changed after freeze"
    evidence = {"cwd": str(repo), "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=repo, text=True).strip(),
        "source_sha256": source, "fingerprint_convention": "SHA256 of UTF-8 sorted compact JSON path-to-file-SHA256 manifest; distinct from Python filename-NUL-content fingerprint",
        "files": files, "source_freeze_verified": bool(args.verify_source)}
    if args.binary:
        evidence["binary"] = {"path": str(args.binary.resolve()), "bytes": args.binary.stat().st_size,
            "sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2)+"\n")
    print(json.dumps({k: v for k, v in evidence.items() if k != "files"}))


if __name__ == "__main__":
    main()
