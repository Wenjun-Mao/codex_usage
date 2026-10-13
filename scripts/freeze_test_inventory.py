"""Generate a reviewable frozen case registry from an already qualified JUnit run."""
import argparse
import json
from pathlib import Path
from xml.etree import ElementTree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit", type=Path)
    parser.add_argument("--kind", choices=("python", "extension"), required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tests = list(ElementTree.parse(args.junit).getroot().iter("testcase"))
    if not tests or any(test.find(tag) is not None for test in tests for tag in ("failure", "error")):
        raise ValueError("Baseline must be an already qualified passing suite")
    values = [(test.get("classname"), test.get("name")) if args.kind == "python" else test.get("name") for test in tests]
    if len(values) != len(set(values)):
        raise ValueError("Baseline contains duplicate case identities")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"schema": 1, "source_sha": args.source_sha, "required": sorted(values)},
        sort_keys=True, separators=(",", ":")) + "\n")
    print(f"Frozen {len(values)} unique {args.kind} cases from {args.source_sha}")


if __name__ == "__main__":
    main()
