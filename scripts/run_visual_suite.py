"""Run one independently retryable, synthetic visual qualification gate."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from verification.visual_cases import validate_inventory

SCRIPTS = {
    "screenshots-allowance": (("screenshots", "generate_marketplace_screenshot.py", "--check"),
        ("allowance", "check_allowance_ui.py")),
    "speed": (("speed", "check_speed_ui.py"),),
    "breakdown": (("breakdown", "check_usage_breakdown_ui.py"),),
    "overlay": (("overlay", "check_breakdown_overlay_ui.py"),),
    "hover": (("hover", "check_breakdown_hover_ui.py"),),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=SCRIPTS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fail-case", default="", help="Explicit case-key fault injection; nonpublishing probes only")
    args = parser.parse_args()
    environment = {**os.environ, "CODEX_VISUAL_FAIL_CASE": args.fail_case}
    for suite, script, *flags in SCRIPTS[args.suite]:
        directory = args.output / suite
        subprocess.run([sys.executable, str(Path(__file__).with_name(script)), *flags,
            "--output", str(directory)], env=environment, check=True)
        validate_inventory(json.loads((directory / "verification.json").read_text()), suite)


if __name__ == "__main__":
    main()
