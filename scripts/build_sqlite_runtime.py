"""Build official SQLite into an isolated CPython; never modify shared uv Python.

macOS/Linux: uv run python scripts/build_sqlite_runtime.py
Then: uv sync --python build/sqlite-runtime/install/bin/python3.13 --group package
Windows package builds must use a native Python linked to the same pinned engine;
this script intentionally refuses cross-compilation rather than claiming coverage.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from runtime_sources import OPENSSL, PYTHON, SQLITE, prepare, verify_archive


ROOT = Path(__file__).resolve().parents[1]


def artifacts(prefix):
    result = {}
    for path in sorted(prefix.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            with path.open('rb') as stream:
                result[path.relative_to(prefix).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def run(arguments, *, cwd, env, log):
    print("Building:", " ".join(map(str, arguments)), flush=True)
    with log.open("ab") as output:
        subprocess.run(list(map(str, arguments)), cwd=cwd, env=env,
                       stdout=output, stderr=subprocess.STDOUT, check=True)


def validate_saved(saved, root):
    if (saved.get('sources') != [asdict(source) for source in (SQLITE, PYTHON, OPENSSL)]
            or saved.get('artifacts') != artifacts(root / 'install')):
        raise ValueError('Runtime inputs/artifacts changed; rebuild into a fresh --output directory')
    inputs = saved.get('native_inputs')
    if not isinstance(inputs, dict) or len(inputs) != 3:
        raise ValueError('Missing native input provenance; use a fresh --output directory')
    for relative, expected in inputs.items():
        path = root / relative
        if (not path.resolve().is_relative_to(root) or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise ValueError('Native build input changed; use a fresh --output directory')
    for source in (SQLITE, PYTHON, OPENSSL):
        verify_archive(source, root)


def build(root, jobs):
    if sys.platform == "win32":
        raise ValueError("Use a native Windows SQLite/Python build, not this POSIX builder")
    root = root.absolute()
    if root.is_symlink() or root.parent.resolve() != root.parent:
        raise ValueError("Runtime output must have a canonical nonsymlink parent")
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < 2 * 1024**3:
        raise ValueError("Reserve at least 2 GiB for the isolated native build")
    prefix = root / "install"
    python = prefix / "bin/python3.13"
    manifest = root / "manifest.json"
    if manifest.exists():
        saved = json.loads(manifest.read_text())
        validate_saved(saved, root)
        subprocess.run([str(python), str(ROOT / "scripts/check_sqlite_runtime.py")],
                       env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, check=True)
        return python
    if prefix.exists():
        raise ValueError('Incomplete runtime output; choose a fresh --output directory')
    log = root / "build.log"
    ssl_source, sqlite_source, python_source = (prepare(source, root) for source in (OPENSSL, SQLITE, PYTHON))
    native_inputs = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in (sqlite_source / name for name in ('sqlite3.c', 'sqlite3.h', 'sqlite3ext.h'))}
    env = dict(os.environ)
    if sys.platform == "darwin":
        env.setdefault("MACOSX_DEPLOYMENT_TARGET", "11.0")
    prefix.mkdir(exist_ok=True)
    run(["perl", "Configure", "no-shared", "no-tests", f"--prefix={prefix}",
         "--openssldir=/etc/ssl", "--libdir=lib"],
        cwd=ssl_source, env=env, log=log)
    run(["make", f"-j{jobs}", "build_libs"], cwd=ssl_source, env=env, log=log)
    run(["make", "install_dev"], cwd=ssl_source, env=env, log=log)
    flags = ["-O3", "-fPIC", "-DSQLITE_THREADSAFE=1", "-DSQLITE_ENABLE_DBSTAT_VTAB",
             "-DSQLITE_ENABLE_FTS3", "-DSQLITE_ENABLE_FTS3_PARENTHESIS", "-DSQLITE_ENABLE_FTS4",
             "-DSQLITE_ENABLE_FTS5", "-DSQLITE_ENABLE_RTREE", "-DSQLITE_ENABLE_MATH_FUNCTIONS",
             "-DSQLITE_DEFAULT_AUTOVACUUM=0", "-DSQLITE_MAX_DEFAULT_PAGE_SIZE=8192"]
    sqlite_object = root / "sqlite3.o"
    run([env.get("CC", "cc"), *flags, "-c", sqlite_source / "sqlite3.c", "-o", sqlite_object],
        cwd=root, env=env, log=log)
    library = prefix / "lib/libsqlite3.a"
    run(["ar", "rcs", library, sqlite_object], cwd=root, env=env, log=log)
    shutil.copy2(sqlite_source / "sqlite3.h", prefix / "include/sqlite3.h")
    shutil.copy2(sqlite_source / "sqlite3ext.h", prefix / "include/sqlite3ext.h")
    env.update(LIBSQLITE3_CFLAGS=f"-I{prefix}/include", LIBSQLITE3_LIBS=f"{library} -lm",
               CFLAGS="-O3", LDFLAGS=f"-Wl,-rpath,{prefix}/lib")
    python_build = root / "python-build"
    python_build.mkdir(exist_ok=True)
    run([python_source / "configure", f"--prefix={prefix}", "--enable-shared",
         "--enable-optimizations", "--with-lto", "--with-ensurepip=no", "--with-pkg-config=no",
         f"--with-openssl={prefix}", "--with-openssl-rpath=auto"], cwd=python_build, env=env, log=log)
    run(["make", f"-j{jobs}"], cwd=python_build, env=env, log=log)
    run(["make", "install"], cwd=python_build, env=env, log=log)
    result = subprocess.run([str(python), str(ROOT / "scripts/check_sqlite_runtime.py")],
                            env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, check=True,
                            text=True, capture_output=True)
    subprocess.run([str(python), '-c',
        "from urllib.request import urlopen; "
        "response=urlopen('https://www.sqlite.org/download.html',timeout=30); response.close()"], check=True)
    for relative, expected in native_inputs.items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
            raise ValueError('Native build input changed during construction')
    for source in (SQLITE, PYTHON, OPENSSL):
        verify_archive(source, root)
    manifest.write_text(json.dumps({"platform": platform.platform(), "runtime": json.loads(result.stdout),
        "sources": [asdict(source) for source in (SQLITE, PYTHON, OPENSSL)],
        "native_inputs": native_inputs, "artifacts": artifacts(prefix)}, indent=2) + "\n")
    print(result.stdout, end="")
    return python


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/sqlite-runtime")
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    python = build(args.output, args.jobs)
    print(f"Runtime ready: {python}")


if __name__ == "__main__":
    main()
