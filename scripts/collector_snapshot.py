"""Create a private, coherent, read-only-input ledger benchmark snapshot."""
import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from time import monotonic


def snapshot(source: Path, output: Path, *, timeout=30):
    source = source.resolve(strict=True)
    if output.exists():
        raise ValueError("snapshot destination already exists")
    if shutil.disk_usage(output.parent).free < max(8 * 1024**3, source.stat().st_size * 4):
        raise OSError("insufficient private benchmark disk budget")
    output.mkdir(mode=0o700)
    target = output / "input.sqlite3"
    started = monotonic()

    def progress(status, remaining, total):
        if monotonic() - started > timeout:
            raise TimeoutError("read-only snapshot exceeded its deadline")

    try:
        with sqlite3.connect(source.as_uri()+"?mode=ro", uri=True, timeout=1) as reader:
            with sqlite3.connect(target) as writer:
                reader.backup(writer, pages=2048, progress=progress, sleep=.01)
                if writer.execute("pragma quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("snapshot quick check failed")
        target.chmod(0o600)
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        result = {"private_input": True, "input_access": "SQLite mode=ro backup only",
            "source": str(source), "snapshot_sha256": digest,
            "snapshot_bytes": target.stat().st_size,
            "frozen_now": datetime.now(UTC).isoformat(),
            "backup_seconds": monotonic()-started}
        manifest = output / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2)+"\n")
        manifest.chmod(0o600)
        return result
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = snapshot(args.ledger, args.output)
    print(json.dumps({key: value for key, value in result.items() if key != "source"}))


if __name__ == "__main__":
    main()
