"""Exercise Node's actual test event transport, including successful TODO exits."""
import json
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("modifier", ["", ".skip", ".todo"])
def test_reporter_preserves_runner_completion_collection_and_nonpassing_flags(tmp_path, modifier):
    test = tmp_path / "sample.test.js"
    test.write_text(f"const test = require('node:test'); test{modifier}('named case', () => {{}});\n")
    reporter = Path(__file__).resolve().parents[1] / "extensions/vscode/scripts/qualification-reporter.cjs"
    result = subprocess.run(["node", "--test", f"--test-reporter={reporter}", str(test)],
        cwd=tmp_path, text=True, capture_output=True, check=True)
    evidence = json.loads(result.stdout)
    assert evidence["complete"] is True
    assert evidence["collected"] == [["sample.test.js", "named case"]]
    assert evidence["cases"] == [{"identity": ["sample.test.js", "named case"], "outcome": "passed",
        "skipped": modifier == ".skip", "todo": modifier == ".todo"}]
    assert evidence["summaries"][0]["counts"]["tests"] == 1
