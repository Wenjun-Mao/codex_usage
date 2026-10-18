"""Private progress and local locks have no publication authority."""
import json

from filelock import Timeout
import pytest

from release_tooling_support import load_tool

state = load_tool("release.process_state")
tag = load_tool("release.process_tag")


def test_progress_lock_atomicity_and_candidate_binding(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "ROOT", tmp_path)
    first = state.Progress(tmp_path / "output/process", {"sha": "a"})
    with first.locked():
        first.mark("prepared")
        with pytest.raises(Timeout):
            with state.Progress(tmp_path / "output/other", {"sha": "a"}).locked():
                pytest.fail("overlap")
    assert json.loads(first.path.read_text())["status"] == "prepared"
    with pytest.raises(ValueError, match="differs"):
        with state.Progress(first.directory, {"sha": "b"}).locked():
            pass
    with first.locked():
        with pytest.raises(RuntimeError):
            with first.phase("interrupted"):
                raise RuntimeError()
        assert first.data["timings"][-1]["status"] == "interrupted-or-failed"


def test_publication_intent_recovered_across_output_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "ROOT", tmp_path)
    with state.Progress(tmp_path / "output/first", {"sha": "a"}).locked() as first:
        first.data["operations"]["promotion"] = {"request_id": "original-accepted-request"}
        first.save()
    with state.Progress(tmp_path / "output/other", {"sha": "a"}).locked() as other:
        assert other.data["operations"]["promotion"]["request_id"] == "original-accepted-request"
        other.data["operations"]["promotion"]["run"] = 77
        other.save()
    with first.locked():
        assert first.data["operations"]["promotion"]["run"] == 77


def test_altered_local_operation_cannot_replace_canonical_intent(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "ROOT", tmp_path)
    with state.Progress(tmp_path / "output/first", {"sha": "a"}).locked() as first:
        first.data["operations"]["promotion"] = {"request_id": "original"}
        first.save()
    data = json.loads(first.path.read_text())
    data["operations"]["promotion"] = {"request_id": "tampered"}
    first.path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="canonical intent"):
        with first.locked():
            pass


@pytest.mark.parametrize("target_local", [False, True])
def test_canonical_filename_symlink_is_refused_before_saving(tmp_path, monkeypatch, target_local):
    monkeypatch.setattr(state, "ROOT", tmp_path)
    progress = state.Progress(tmp_path / "output/process", {"sha": "a"})
    target = progress.path if target_local else tmp_path / "unrelated.json"
    before = json.dumps({"schema": 1, "candidate": {"sha": "a"}, "operations": {}, "timings": []})
    target.write_text(before)
    progress.shared.symlink_to(target)
    with pytest.raises(ValueError, match="Symlinked canonical"):
        with progress.locked():
            pass
    assert target.read_text() == before


def test_canonical_parent_escape_and_predictable_temp_symlink_are_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "ROOT", tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = tmp_path / "output/releases"
    parent.mkdir(parents=True)
    (parent / "process-intents").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escape"):
        state.Progress(tmp_path / "output/process", {})
    target = outside / "untouched"
    target.write_text("keep")
    destination = parent / "generated.json"
    destination.with_suffix(".json.tmp").symlink_to(target)
    state.atomic_json(destination, {"safe": True})
    assert target.read_text() == "keep" and json.loads(destination.read_text()) == {"safe": True}


def test_output_escape_and_local_publisher_credentials_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "ROOT", tmp_path)
    with pytest.raises(ValueError):
        state.Progress(tmp_path / "not-output", {})
    monkeypatch.setenv("VSCE_PAT", "must-not-print")
    with pytest.raises(ValueError, match="credentials"):
        state.command(["false"])


def test_lost_tag_push_stays_pending_and_remote_matching_readback_is_safe(tmp_path, monkeypatch):
    from types import SimpleNamespace
    progress = SimpleNamespace(candidate={"version": "2.12.6", "sha": "a" * 40}, data={"operations": {}}, save=lambda: None)
    monkeypatch.setattr(tag, "remote_tag", lambda *a: None)
    monkeypatch.setattr(tag, "git", lambda *a: "")
    calls = []
    def lost(args):
        calls.append(args)
        if args[1] == "push":
            raise TimeoutError()
    with pytest.raises(state.Pending, match="reply unknown"):
        tag.ensure_tag(progress, None, allow=True, run_command=lost)
    with pytest.raises(state.Pending, match="attempted"):
        tag.ensure_tag(progress, None, allow=True, run_command=lost)
    assert len(calls) == 2
    monkeypatch.setattr(tag, "remote_tag", lambda *a: "a" * 40)
    assert tag.ensure_tag(progress, None) == "v2.12.6" and len(calls) == 2
    monkeypatch.setattr(tag, "remote_tag", lambda *a: "b" * 40)
    with pytest.raises(ValueError, match="never move"):
        tag.ensure_tag(progress, None, allow=True, run_command=lost)
