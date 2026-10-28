"""Portable policy/provenance tests; these do not qualify a Windows runtime."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from release_tooling_support import load_tool


builder = load_tool("build_sqlite_runtime_windows")
sources = load_tool("runtime_windows_sources")


def package(tmp_path, extra=None):
    archive = tmp_path / "python.nupkg"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, body in {"python.nuspec": "metadata", "tools/python.exe": "official",
                           **(extra or {})}.items():
            bundle.writestr(name, body)
    return sources.Source(archive.as_uri(), "sha256",
                          hashlib.sha256(archive.read_bytes()).hexdigest(), "tools")


def test_nuget_extracts_fresh_tools_only(tmp_path):
    source = package(tmp_path)
    root = tmp_path / "build"
    first = sources.prepare_python(root, source)
    (first / "python.exe").write_text("locally modified")
    second = sources.prepare_python(root, source)
    assert second != first
    assert (second / "python.exe").read_text() == "official"
    assert list(second.iterdir()) == [second / "python.exe"]
    assert not list((root / "sources").glob("nuget-*"))


@pytest.mark.parametrize("name", ["../escape", "/absolute", "tools/../escape",
                                       "tools/C:ads", "tools\\..\\escape", "C:/escape"])
def test_nuget_rejects_unsafe_paths(tmp_path, name):
    source = package(tmp_path, {name: "bad"})
    with pytest.raises(ValueError, match="Unsafe"):
        sources.prepare_python(tmp_path / "build", source)
    assert list((tmp_path / "build/sources").iterdir()) == []


def test_nuget_rechecks_cached_archive(tmp_path):
    source = package(tmp_path)
    root = tmp_path / "build"
    sources.prepare_python(root, source)
    (root / "downloads/python.nupkg").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum mismatch"):
        sources.prepare_python(root, source)


def test_command_is_x64_unmodified_amalgamation_with_required_features(tmp_path):
    command = builder.command(tmp_path / "source", tmp_path / "native", "cl.exe")
    assert "/MACHINE:X64" in command
    assert "/DSQLITE_THREADSAFE=1" in command
    assert "/DSQLITE_ENABLE_DBSTAT_VTAB" in command
    assert "/DSQLITE_API=__declspec(dllexport)" in command
    assert str(tmp_path / "source/sqlite3.c") in command
    assert not any("/D" in arg and "SQLITE_VERSION" in arg for arg in command)


def test_output_must_stay_under_private_canonical_build(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    assert builder.private_output(tmp_path / "build/runtime") == tmp_path / "build/runtime"
    for path in (tmp_path, tmp_path / "build", tmp_path / "outside"):
        with pytest.raises(ValueError, match="under build"):
            builder.private_output(path)
    (tmp_path / "build").mkdir()
    (tmp_path / "build/link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="nonsymlink"):
        builder.private_output(tmp_path / "build/link/runtime")


def test_non_windows_fails_before_preparation(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "sys", SimpleNamespace(platform="darwin"))
    with pytest.raises(ValueError, match="native Windows x64"):
        builder.build(tmp_path / "runtime")
    assert not (tmp_path / "runtime").exists()


def mock_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(builder.platform, "machine", lambda: "AMD64")
    monkeypatch.setenv("VSCMD_ARG_TGT_ARCH", "x64")
    tool = tmp_path / "tool.exe"
    tool.write_bytes(b"mock MSVC")
    monkeypatch.setattr(builder.shutil, "which", lambda name: str(tool))
    root = tmp_path / "build/runtime"

    def sqlite(source, output):
        target = output / "sources/sqlite"
        target.mkdir(parents=True)
        for name in ("sqlite3.c", "sqlite3.h", "sqlite3ext.h"):
            (target / name).write_text(name)
        return target

    def python(output):
        target = output / "sources/python"
        (target / "DLLs").mkdir(parents=True)
        (target / "DLLs/_sqlite3.pyd").write_bytes(b"official binding")
        (target / "DLLs/sqlite3.dll").write_bytes(b"old sqlite")
        (target / "python.exe").write_bytes(b"official interpreter")
        return target

    def run(arguments, output, capture=False):
        if "/DEPENDENTS" in arguments:
            return "sqlite3.dll\npython313.dll"
        (output / "native/sqlite3.dll").write_bytes(b"new sqlite")

    monkeypatch.setattr(builder, "prepare", sqlite)
    monkeypatch.setattr(builder, "prepare_python", python)
    monkeypatch.setattr(builder, "run", run)
    monkeypatch.setattr(builder, "qualify", lambda python, root: {"mock": True})
    return root


def test_mock_build_binds_actual_native_inputs_and_keeps_binding(tmp_path, monkeypatch):
    root = mock_windows(tmp_path, monkeypatch)
    assert builder.build(root) == root / "install/python.exe"
    saved = json.loads((root / "manifest.json").read_text())
    assert saved["sources"] == [asdict(builder.SQLITE), asdict(sources.WINDOWS_PYTHON)]
    assert len(saved["native_inputs"]) == 4
    assert (root / "install/DLLs/_sqlite3.pyd").read_bytes() == b"official binding"
    assert (root / "install/DLLs/sqlite3.dll").read_bytes() == b"new sqlite"
    assert (root / "sources/python/DLLs/sqlite3.dll").read_bytes() == b"old sqlite"
    (root / "sources/sqlite/sqlite3.c").write_text("patched with same version constants")
    with pytest.raises(ValueError, match="Native build input changed"):
        builder.build(root)


def test_artifact_tampering_fails_closed(tmp_path, monkeypatch):
    root = mock_windows(tmp_path, monkeypatch)
    builder.build(root)
    (root / "install/DLLs/sqlite3.dll").write_bytes(b"wrong engine")
    with pytest.raises(ValueError, match="inputs/artifacts changed"):
        builder.build(root)


def test_static_or_unexpected_binding_is_rejected(tmp_path, monkeypatch):
    root = mock_windows(tmp_path, monkeypatch)
    monkeypatch.setattr(builder, "run", lambda *args, **kwargs: "python313.dll only")
    with pytest.raises(ValueError, match="dynamically import"):
        builder.build(root)
    assert not (root / "install").exists()
    assert not (root / "manifest.json").exists()


def test_incomplete_output_is_never_overwritten(tmp_path, monkeypatch):
    root = mock_windows(tmp_path, monkeypatch)
    (root / "install").mkdir(parents=True)
    with pytest.raises(ValueError, match="Incomplete runtime output"):
        builder.build(root)


def test_wrong_msvc_target_fails_before_download(tmp_path, monkeypatch):
    root = mock_windows(tmp_path, monkeypatch)
    monkeypatch.setenv("VSCMD_ARG_TGT_ARCH", "x86")
    with pytest.raises(ValueError, match="MSVC target must be x64"):
        builder.build(root)
    assert not (root / "sources").exists()


def test_in_flight_source_mutation_never_publishes_manifest(tmp_path, monkeypatch):
    root = mock_windows(tmp_path, monkeypatch)
    original = builder.run

    def mutate(arguments, output, **kwargs):
        result = original(arguments, output, **kwargs)
        if "/DEPENDENTS" not in arguments:
            (root / "sources/sqlite/sqlite3.h").write_text("modified")
        return result

    monkeypatch.setattr(builder, "run", mutate)
    with pytest.raises(ValueError, match="changed during compilation"):
        builder.build(root)
    assert not (root / "manifest.json").exists()
    assert not (root / "install").exists()


def test_runtime_failure_leaves_no_success_manifest(tmp_path, monkeypatch):
    root = mock_windows(tmp_path, monkeypatch)

    def fail(*args):
        raise RuntimeError("wrong loaded engine")

    monkeypatch.setattr(builder, "qualify", fail)
    with pytest.raises(RuntimeError, match="wrong loaded engine"):
        builder.build(root)
    assert not (root / "manifest.json").exists()


def test_reuse_checks_archives_and_never_rebuilds(tmp_path, monkeypatch):
    root = mock_windows(tmp_path, monkeypatch)
    for name in ("SQLITE", "WINDOWS_PYTHON"):
        source = sources.Source(f"https://example.invalid/{name}.zip", "sha256",
                                hashlib.sha256(name.encode()).hexdigest(), name)
        monkeypatch.setattr(builder, name, source)
    builder.build(root)
    (root / "downloads").mkdir()
    for name in ("SQLITE", "WINDOWS_PYTHON"):
        (root / f"downloads/{name}.zip").write_bytes(name.encode())
    monkeypatch.setattr(builder, "prepare", lambda *args: pytest.fail("Must not rebuild"))
    assert builder.build(root) == root / "install/python.exe"
    (root / "downloads/SQLITE.zip").write_bytes(b"modified")
    with pytest.raises(ValueError, match="archive checksum mismatch"):
        builder.build(root)


def test_runtime_probe_checks_actual_loaded_dll_and_dbstat():
    compile(builder.PROBE, "<probe>", "exec")
    assert "GetModuleFileNameW" in builder.PROBE
    assert "_sqlite3.__file__" in builder.PROBE
    assert "pathlib.Path(sys.argv[2]).resolve()" in builder.PROBE
    assert "select sum(pgsize) from dbstat" in builder.PROBE
    assert '"THREADSAFE=1"' in builder.PROBE


@pytest.mark.parametrize("filename", ["build-agent-windows-x64.ps1", "build-windows-exe.ps1"])
def test_package_scripts_prepare_then_use_private_runtime(filename):
    script = (Path(__file__).resolve().parents[1] / "scripts" / filename).read_text()
    assert script.index("Initialize-WindowsSqliteRuntime -RepoRoot") < script.index("uv sync --locked")
    assert "uv sync --locked --python $runtimePython --group package" in script
    assert "uv run --no-sync pyinstaller" in script
    assert '--check-python (Join-Path $env:UV_PROJECT_ENVIRONMENT "Scripts\\python.exe")' in script
    assert "$env:UV_PROJECT_ENVIRONMENT = $previousProjectEnvironment" in script
    assert all("--no-sync" in line for line in script.splitlines() if "uv run " in line)
