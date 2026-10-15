"""Frozen summaries do not replace a fresh read of the raw hover artifact."""
import pytest

from qualification_fixture import FixtureAPI, policy


def corrupt_hover_payload(api):
    row = next(row for row in api.uploads if row["name"].startswith("payload-visual-hover-"))
    api.bodies[f"{api.prefix}/actions/artifacts/{row['id']}/zip"] += b"changed after upload"
    api._cache.clear()


@pytest.mark.parametrize("stage", ["freeze", "hosted-inspect"])
def test_raw_hover_payload_is_required_at_both_independent_validation_stages(stage):
    api = FixtureAPI()
    if stage == "hosted-inspect":
        manifest = api.reader().freeze()
        api.add_gate("hosted", {"hosted.json": policy.canonical(manifest)})
    corrupt_hover_payload(api)
    with pytest.raises(ValueError, match="Downloaded artifact digest/size mismatch"):
        getattr(api.reader(), "hosted" if stage == "hosted-inspect" else "freeze")()
