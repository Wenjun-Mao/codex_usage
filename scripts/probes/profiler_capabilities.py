"""Read-only profiler preflight on the isolated hosted diagnostic runner."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probes.webkit_process_sample import require_ephemeral_host  # noqa: E402

COMMANDS = {
    "locate": ("/usr/bin/xcrun", "--find", "xctrace"),
    "version": ("/usr/bin/xcrun", "xctrace", "version"),
    "record-help": ("/usr/bin/xcrun", "xctrace", "help", "record"),
    "export-help": ("/usr/bin/xcrun", "xctrace", "help", "export"),
    "templates": ("/usr/bin/xcrun", "xctrace", "list", "templates"),
}
OUTPUT_LIMIT = 64 * 1024


def collect(output):
    require_ephemeral_host()
    output.mkdir(parents=True, exist_ok=True)
    # Profiler helpers do not receive repository/publisher tokens or task context.
    environment = {key: os.environ[key] for key in
        ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "DEVELOPER_DIR") if key in os.environ}
    evidence = {"diagnostic_only": True, "process_attachment": False,
        "utc": datetime.now(timezone.utc).isoformat(), "commands": {}}
    for name, command in COMMANDS.items():
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                env=environment, timeout=10, check=False)
            text = result.stdout + result.stderr
            row = {"exit_code": result.returncode, "truncated": len(text) > OUTPUT_LIMIT}
            (output / f"{name}.txt").write_text(text[:OUTPUT_LIMIT])
        except (OSError, subprocess.TimeoutExpired) as error:
            row = {"unavailable": type(error).__name__}
        evidence["commands"][name] = row
        if name == "locate" and row.get("exit_code") != 0:
            break
    evidence["status"] = "available" if len(evidence["commands"]) == len(COMMANDS) and all(
        row.get("exit_code") == 0 and not row.get("truncated")
        for row in evidence["commands"].values()) else "unavailable"
    (output / "capabilities.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    evidence = collect(parser.parse_args().output)
    print(json.dumps({"profiler_preflight": evidence["status"], "process_attachment": False}))


if __name__ == "__main__":
    main()
