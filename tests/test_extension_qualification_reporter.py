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
    result = subprocess.run(["node", "--test", f"--test-reporter={reporter.as_uri()}", str(test)],
        cwd=tmp_path, text=True, capture_output=True, check=True)
    evidence = json.loads(result.stdout)
    assert evidence["complete"] is True
    assert evidence["collected"] == [["sample.test.js", "named case"]]
    assert evidence["cases"] == [{"identity": ["sample.test.js", "named case"], "outcome": "passed",
        "skipped": modifier == ".skip", "todo": modifier == ".todo"}]
    assert evidence["summaries"][0]["counts"]["tests"] == 1


def test_qualification_entrypoint_loads_custom_reporter_as_a_file_url(tmp_path):
    entrypoint = Path(__file__).resolve().parents[1] / "extensions/vscode/scripts/test-qualification.js"
    program = """
const fs = require('node:fs');
const childProcess = require('node:child_process');
const path = require('node:path');
const calls = [];
childProcess.execFileSync = (executable, args) => calls.push({executable, args});
require(path.join(path.dirname(process.argv[1]), 'cliEntrypoints')).npmCliPath = () => '/fixture/npm-cli.js';
fs.mkdirSync = () => {};
fs.readdirSync = () => ['one.test.js'];
const readFile = fs.readFileSync;
fs.readFileSync = (file, ...args) => String(file).endsWith('extension-inventory.json')
  ? JSON.stringify({summaries: [], complete: true}) : readFile(file, ...args);
process.argv = ['node', process.argv[1], process.argv[2]];
require(process.argv[1]);
console.log(JSON.stringify(calls));
"""
    result = subprocess.run(["node", "-e", program, str(entrypoint), str(tmp_path / "tests.xml")],
        text=True, capture_output=True, check=True)
    calls = json.loads(result.stdout.splitlines()[-1])
    assert len(calls) == 2
    assert calls[1]["args"][0] == "--test"
    reporter = next(arg.split("=", 1)[1] for arg in calls[1]["args"]
        if arg.startswith("--test-reporter=") and arg != "--test-reporter=junit")
    assert reporter == entrypoint.with_name("qualification-reporter.cjs").as_uri()
