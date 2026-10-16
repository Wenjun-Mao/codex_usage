"""Nonpublishing native runtime compatibility on fresh CI, never a live collector."""
import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import runpy
import shutil
import sys
import sysconfig
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def require_disposable_host():
    from codex_usage.codex_registration import discover_codex_executables
    if os.environ.get("GITHUB_ACTIONS") != "true" or any(
            shutil.which(candidate) for candidate in discover_codex_executables()):
        raise RuntimeError("frozen experiment requires fresh CI without any account CLI")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    require_disposable_host()
    from codex_usage.agent_watcher import DirtyPathSet, SessionWatcher
    import pydantic_core
    from codex_usage.settings import AppSettings
    assert pydantic_core and AppSettings
    with tempfile.TemporaryDirectory(prefix="runtime-watcher-") as raw:
        root = Path(raw).resolve()
        dirty = DirtyPathSet()
        watcher = SessionWatcher([root], dirty, on_overflow=lambda: None)
        try:
            watcher.start()
            path = root / "synthetic.jsonl"
            path.write_text("{}\n")
            deadline = time.monotonic()+10
            while time.monotonic() < deadline and str(path) not in dirty.snapshot():
                time.sleep(.02)
            assert str(path) in dirty.snapshot(), "native watcher did not deliver a file event"
        finally:
            watcher.stop()
        assert not watcher.is_alive()
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"),
        PYINSTALLER_CONFIG_DIR=str(output / "pyinstaller-cache"))
    from codex_usage.process_tree import run_process_tree
    def run(command, timeout=120):
        result = run_process_tree(command, environment=environment, cwd=ROOT, timeout_seconds=timeout)
        if result.returncode:
            raise RuntimeError(result.stdout+result.stderr)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
        "--name", "codex-usage-agent", "--paths", str(ROOT / "src"), "--distpath", str(output / "bin"),
        "--workpath", str(output / "work"), "--specpath", str(output), str(ROOT / "src/codex_usage/agent_main.py")])
    executable = output / "bin" / ("codex-usage-agent.exe" if os.name == "nt" else "codex-usage-agent")
    # The smoke owns its driver/tree directly; another outer subprocess timeout
    # must not lose ownership when that driver creates its own process group.
    old_argv = sys.argv
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        sys.argv = ["smoke", "--executable", str(executable),
                    "--parallel-evidence", str(output / "collector-parallel.json")]
        try:
            runpy.run_path(str(ROOT / "scripts/smoke-test-packaged-agent.py"), run_name="__main__")
        except SystemExit as error:
            if error.code not in (None, 0):
                raise
    finally:
        sys.argv = old_argv
    with executable.open("rb") as stream:
        collector_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    data = {"experiment_only": True, "source": os.environ["GITHUB_SHA"], "python": sys.version,
        "machine": platform.machine(), "platform": sys.platform, "compiler": platform.python_compiler(),
        "gil_enabled": sys._is_gil_enabled(), "free_threaded_build": sysconfig.get_config_var("Py_GIL_DISABLED"),
        "jit_enabled": bool(getattr(sys, "_jit", None) and sys._jit.is_enabled()),
        "dependencies": {name: version(name) for name in ("pydantic", "pydantic-core", "watchdog", "pyinstaller", "pyinstaller-hooks-contrib")},
        "native_watcher": "event observed and shutdown joined", "collector_sha256": collector_sha,
        "collector_bytes": executable.stat().st_size}
    (output / "runtime.json").write_text(json.dumps(data, indent=2)+"\n")
    print(json.dumps(data))


if __name__ == "__main__":
    main()
