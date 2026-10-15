"""Producer, freeze and inspection all check current independently pinned history."""
from copy import deepcopy

import pytest

from qualification_fixture import FixtureAPI, policy
from latency_binding_fixture import latency, successor


def test_frozen_and_inspected_manifests_preserve_the_exact_explicit_disposition():
    api = FixtureAPI()
    manifest = api.reader().freeze()
    assert manifest["timing_disposition"] == latency.SCOPE["disposition"]
    assert manifest["latency_binding"] == api.hover["timing_context"]["binding"]
    proof = api.reader().resolve("visual-hover", payload=True)["receipt"]["manifest"]["visual"]["hover"]
    assert proof["schema"] == 2 and proof["status"] == "functional-complete"
    assert proof["observation_summary"]["status"] == "deferred-known-latency"
    assert proof["observation_summary"]["deferred_observations"] == 216
    api.add_gate("hosted", {"hosted.json": policy.canonical(manifest)})
    assert api.reader().hosted()[1] == manifest


@pytest.mark.parametrize("stage", ["receipt", "freeze", "inspect"])
def test_superseded_proof_never_becomes_current_qualification(stage):
    api = FixtureAPI()
    if stage == "inspect":
        manifest = api.reader().freeze()
        api.add_gate("hosted", {"hosted.json": policy.canonical(manifest)})
    journal = api.journal
    row = journal.read()["records"][-1]
    value = successor(row["event"]["binding"], api.hover["timing_context"]["binding"], sha="e"*40)
    journal.anchor(journal.candidate(latency.binding_event(value, journal.config)))
    with pytest.raises(ValueError, match="another source"):
        reader = api.reader()
        if stage == "receipt":
            reader.resolve("visual-hover")
        else:
            getattr(reader, "hosted" if stage == "inspect" else "freeze")()


@pytest.mark.parametrize("fault", ["context", "fast-pass", "missing-summary", "count"])
def test_receipt_summary_cannot_forge_an_approval_or_hide_deferral(fault):
    api = FixtureAPI()
    def mutate(receipt):
        hover = receipt["manifest"]["visual"]["hover"]
        if fault == "context":
            hover["timing_context"]["origin"]["attempt"] = 2
        elif fault == "fast-pass":
            hover["observation_summary"]["status"] = "passed"
        elif fault == "count":
            hover["observation_summary"]["deferred_observations"] = 0
        else:
            hover.pop("observation_summary")
    api.rewrite_receipt("visual-hover", mutate)
    with pytest.raises(ValueError):
        api.reader().resolve("visual-hover")


@pytest.mark.parametrize("fault", ["binding", "disposition"])
def test_frozen_manifest_cannot_substitute_another_binding_or_pass_label(fault):
    api = FixtureAPI()
    manifest = api.reader().freeze()
    if fault == "binding":
        manifest["latency_binding"] = deepcopy(manifest["latency_binding"])
        manifest["latency_binding"]["binding_sha256"] = "e"*64
    else:
        manifest["timing_disposition"] = "passed"
    api.add_gate("hosted", {"hosted.json": policy.canonical(manifest)})
    with pytest.raises(ValueError):
        api.reader().hosted()
