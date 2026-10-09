#!/usr/bin/env python3
"""Disposable content-free RPC fixture; never dispatches to a real Codex binary."""
import json
import os
from pathlib import Path
import sys

fixture = Path(os.environ["CODEX_BREAKDOWN_RPC_FIXTURE"])
assert fixture.parent.name.startswith("speed-native-")
assert Path(os.environ["CODEX_HOME"]).resolve() == fixture.parent / "codex"
results = json.loads(fixture.read_text())
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    assert method in {"initialize", "account/read", "account/rateLimits/read", "account/usage/read"}
    print(json.dumps({"id": request["id"], "result": results.get(method, {})}), flush=True)
