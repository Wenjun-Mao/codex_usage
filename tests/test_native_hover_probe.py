"""Diagnostic observation must preserve CDP arguments, errors and class restoration."""
import json
from types import SimpleNamespace

import pytest

from release_tooling_support import load_tool

probe = load_tool("probes.native_hover_latency")


@pytest.mark.parametrize("fails", (False, True))
def test_protocol_trace_observes_existing_replies_without_extra_calls(fails):
    calls = []

    class Target:
        sequence = 0
        session_id = "synthetic"

        def __init__(self):
            self.session = SimpleNamespace(send=self.outer)

        def outer(self, method, params):
            calls.append((method, params))
            self._received({"sessionId": self.session_id, "message": json.dumps({"id": self.sequence})})
            return {"computedStyle": [{"name": "visibility", "value": "visible"}, {"name": "opacity", "value": "1"}]}

        def _received(self, event):
            calls.append(("received", event))

        def send(self, method, params=None):
            self.sequence += 1
            result = self.session.send("Target.sendMessageToTarget", {"method": method, "params": params})
            if fails:
                raise RuntimeError("original failure")
            return result

    original_send, original_received = Target.send, Target._received
    target, rows = Target(), []
    original_outer = target.session.send
    with probe.protocol_trace(Target, rows):
        if fails:
            with pytest.raises(RuntimeError, match="original failure"):
                target.send("CSS.getComputedStyleForNode", {"nodeId": 7})
        else:
            result = target.send("CSS.getComputedStyleForNode", {"nodeId": 7})
            assert result["computedStyle"][0]["value"] == "visible"
    assert Target.send is original_send and Target._received is original_received
    assert target.session.send is original_outer
    assert len(calls) == 2 and len(rows) == 1
    assert calls[0] == ("Target.sendMessageToTarget", {"method": "CSS.getComputedStyleForNode", "params": {"nodeId": 7}})
    row = rows[0]
    assert row["started_ms"] <= row["iframe_reply_ms"] <= row["outer_ack_ms"] <= row["completed_ms"]
    if fails:
        assert row["failure"] == "RuntimeError: original failure"
    else:
        assert row["style"] == {"visibility": "visible", "opacity": "1"}


def test_diagnostic_workflow_cannot_record_qualification_or_publish():
    text = (probe.SCRIPTS.parent / ".github/workflows/native-hover-probe.yml").read_text()
    assert "contents: read" in text and "persist-credentials: false" in text
    assert "arm: [plain, traced]" in text and "fail-fast: false" in text
    assert "fetch-native" in text and "if: always()" in text
    for forbidden in ("VSCE_PAT", "contents: write", "record-gate", "publication_intent", "validate-publication"):
        assert forbidden not in text
