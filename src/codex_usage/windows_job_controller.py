from __future__ import annotations

import subprocess
import sys

_LAUNCH_GATE = b"1"


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) < 2 or arguments[0] != "--":
        return 125
    if sys.stdin.buffer.read(1) != _LAUNCH_GATE:
        return 125
    try:
        process = subprocess.Popen(
            arguments[1:],
            stdin=subprocess.DEVNULL,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    except OSError:
        return 125
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
