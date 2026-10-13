"""Measure public browser transport while preserving a complete visual gate."""
import argparse
from collections import defaultdict
from functools import wraps
from hashlib import sha256
import json
from pathlib import Path
import runpy
import sys
from time import perf_counter

from playwright.sync_api import Locator, Page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path, default=Path(__file__).with_name("check_usage_breakdown_ui.py"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    script = args.script.resolve()
    stats = defaultdict(lambda: {"calls": 0, "seconds": 0.0, "maximum_seconds": 0.0})
    originals = []

    def instrument(owner, name):
        original = getattr(owner, name)
        label = owner.__name__ + "." + name

        @wraps(original)
        def timed(*values, **keywords):
            started = perf_counter()
            try:
                return original(*values, **keywords)
            finally:
                seconds = perf_counter() - started
                row = stats[label]
                row["calls"] += 1
                row["seconds"] += seconds
                row["maximum_seconds"] = max(row["maximum_seconds"], seconds)

        originals.append((owner, name, original))
        setattr(owner, name, timed)

    for owner, methods in ((Page, ("goto", "evaluate", "set_viewport_size")),
        (Locator, ("evaluate", "evaluate_all", "count", "get_attribute", "focus", "press", "screenshot", "inner_text", "is_visible"))):
        for method in methods:
            instrument(owner, method)
    sys.path.insert(0, str(Path(__file__).parent.resolve()))
    previous = sys.argv
    sys.argv = [str(script), "--output", str(args.output / "visual")]
    started = perf_counter()
    passed = False
    try:
        runpy.run_path(str(script), run_name="__main__")
        passed = True
    finally:
        sys.argv = previous
        for owner, name, original in originals:
            setattr(owner, name, original)
        proof = {"script": str(script), "sha256": sha256(script.read_bytes()).hexdigest(), "passed": passed,
            "elapsed_seconds": perf_counter() - started, "methods": dict(stats),
            "overhead": "Two wall-clock reads and one aggregation per public call; not separately calibrated",
            "scope": "Complete unchanged gate; no filters, timeout changes or assertion bypass"}
        (args.output / "browser-wall.json").write_text(json.dumps(proof, indent=2) + "\n")


if __name__ == "__main__":
    main()
