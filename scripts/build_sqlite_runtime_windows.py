"""Prepare a private official CPython 3.13.16 + SQLite 3.54.1 Windows x64 runtime.

Package PS1 entrypoints discover installed Visual Studio C++ tools/SDK automatically.
For standalone use, run from an x64 MSVC Native Tools prompt:
  uv run python scripts/build_sqlite_runtime_windows.py
No installer, registry edits, global Python changes or CPython source patches.
Only sqlite3.dll in the private PSF NuGet copy is replaced. Upstream references:
https://github.com/python/cpython/blob/v3.13.16/PCbuild/_sqlite3.vcxproj
https://github.com/python/cpython/blob/v3.13.16/PCbuild/sqlite3.vcxproj
https://www.sqlite.org/howtocompile.html#building_a_windows_dll

The manifest binds archives, actual compiler inputs, commands, tool binaries and
runtime artifacts. It is provenance, not a claim of byte-reproducible MSVC output.
Native package/frozen qualification remains necessary after preparation.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys

from runtime_sources import SQLITE, prepare
from runtime_windows_sources import WINDOWS_PYTHON, digest, prepare_python


ROOT = Path(__file__).resolve().parents[1]
DEFINES = (
    "SQLITE_THREADSAFE=1", "SQLITE_ENABLE_DBSTAT_VTAB", "SQLITE_ENABLE_MATH_FUNCTIONS",
    "SQLITE_ENABLE_FTS4", "SQLITE_ENABLE_FTS5", "SQLITE_ENABLE_RTREE",
    "SQLITE_OMIT_AUTOINIT", "SQLITE_API=__declspec(dllexport)",
)
# -I prevents ambient PYTHONPATH/site packages from substituting the binding.
PROBE = r'''
import ctypes, json, pathlib, sqlite3, sys, _sqlite3
assert sys.version_info[:3] == (3, 13, 16), sys.version
assert sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8
prefix = pathlib.Path(sys.base_prefix).resolve()
assert prefix == pathlib.Path(sys.argv[2]).resolve(), prefix
assert pathlib.Path(_sqlite3.__file__).resolve() == prefix / "DLLs" / "_sqlite3.pyd"
k = ctypes.WinDLL("kernel32", use_last_error=True)
k.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
k.GetModuleHandleW.restype = ctypes.c_void_p
k.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
k.GetModuleFileNameW.restype = ctypes.c_uint
handle = k.GetModuleHandleW("sqlite3.dll")
assert handle, "_sqlite3 must load a separate sqlite3.dll"
buffer = ctypes.create_unicode_buffer(32768)
length = k.GetModuleFileNameW(handle, buffer, len(buffer))
assert 0 < length < len(buffer)
assert pathlib.Path(buffer.value).resolve() == prefix / "DLLs" / "sqlite3.dll", buffer.value
sys.path.insert(0, sys.argv[1])
from codex_usage.sqlite_runtime import require_release_runtime
identity = require_release_runtime()
assert "THREADSAFE=1" in identity["compile_options"]
with sqlite3.connect(":memory:") as db:
    db.execute("create table qualification(value)")
    db.execute("insert into qualification values (1)")
    assert db.execute("select sum(pgsize) from dbstat").fetchone()[0] > 0
# Verify packaging's standard-library prerequisites, without network/DB access.
import ssl, venv, ctypes.util, multiprocessing, concurrent.futures
print(json.dumps({"sqlite": identity, "python": sys.version, "binding": _sqlite3.__file__,
                  "dll": buffer.value, "openssl": ssl.OPENSSL_VERSION}))
'''


def artifacts(prefix):
    return {path.relative_to(prefix).as_posix(): digest(path)
            for path in sorted(prefix.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}


def command(source, output, compiler):
    return [str(compiler), "/nologo", "/O2", "/MD", "/LD",
            *[f"/D{value}" for value in DEFINES], str(source / "sqlite3.c"),
            f"/Fo{output / 'sqlite3.obj'}", "/link", "/MACHINE:X64",
            f"/OUT:{output / 'sqlite3.dll'}", f"/IMPLIB:{output / 'sqlite3.lib'}"]


def run(arguments, root, *, capture=False):
    env = dict(os.environ)
    # No inherited compiler options or Python path/home may alter the private build.
    for key in tuple(env):
        if key.upper() in {"CL", "_CL_", "LINK", "_LINK_", "PYTHONHOME", "PYTHONPATH"}:
            del env[key]
    with (root / "build.log").open("a", encoding="utf-8") as log:
        log.write(json.dumps(list(map(str, arguments))) + "\n")
        log.flush()
        result = subprocess.run(list(map(str, arguments)), cwd=root, env=env, check=True,
                                text=True, stdout=subprocess.PIPE if capture else log,
                                stderr=log)
        if capture:
            log.write(result.stdout)
        return result.stdout


def qualify(python, root):
    return json.loads(run([python, "-I", "-B", "-c", PROBE, ROOT / "src", root / "install"],
                          root, capture=True))


def private_output(path):
    path = path.absolute()
    build_root = ROOT / "build"
    if (not path.is_relative_to(build_root) or path == build_root
            or path.resolve() != path):
        raise ValueError("Runtime output must be a canonical nonsymlink directory under build/")
    return path


def validate_saved(saved, root):
    if (saved.get("sources") != [asdict(SQLITE), asdict(WINDOWS_PYTHON)]
            or saved.get("defines") != list(DEFINES)
            or saved.get("artifacts") != artifacts(root / "install")):
        raise ValueError("Runtime inputs/artifacts changed; use a fresh --output directory")
    for relative, expected in saved["native_inputs"].items():
        path = root / relative
        if (not path.resolve().is_relative_to(root) or not path.is_file()
                or digest(path) != expected):
            raise ValueError("Native build input changed; use a fresh --output directory")
    # Bind cached archives too; never trust an old extracted tree over its archive.
    for source in (SQLITE, WINDOWS_PYTHON):
        archive = root / "downloads" / source.url.rsplit("/", 1)[1]
        with archive.open("rb") as stream:
            actual = hashlib.file_digest(stream, source.algorithm).hexdigest()
        if actual != source.checksum:
            raise ValueError("Upstream archive checksum mismatch")


def build(output):
    if (sys.platform != "win32" or platform.machine().upper() not in {"AMD64", "X86_64"}
            or struct.calcsize("P") != 8):
        raise ValueError("Preparation requires native Windows x64; cross-compilation is not supported")
    root = private_output(output)
    root.mkdir(parents=True, exist_ok=True)
    prefix = root / "install"
    python = prefix / "python.exe"
    manifest = root / "manifest.json"
    if manifest.exists():
        saved = json.loads(manifest.read_text(encoding="utf-8"))
        validate_saved(saved, root)
        qualify(python, root)
        return python
    if prefix.exists():
        raise ValueError("Incomplete runtime output; use a fresh --output directory")
    compiler, dumpbin = shutil.which("cl.exe"), shutil.which("dumpbin.exe")
    if not compiler or not dumpbin:
        raise ValueError("Use the Visual Studio x64 Native Tools prompt with the Windows SDK")
    if os.environ.get("VSCMD_ARG_TGT_ARCH", "").lower() != "x64":
        raise ValueError("MSVC target must be x64 (VSCMD_ARG_TGT_ARCH=x64)")
    sqlite_source = prepare(SQLITE, root)
    python_source = prepare_python(root)
    inputs = {path.relative_to(root).as_posix(): digest(path)
              for path in (sqlite_source / "sqlite3.c", sqlite_source / "sqlite3.h",
                           sqlite_source / "sqlite3ext.h", python_source / "DLLs/_sqlite3.pyd")}
    dependencies = run([dumpbin, "/DEPENDENTS", python_source / "DLLs/_sqlite3.pyd"],
                       root, capture=True)
    if "sqlite3.dll" not in dependencies.lower():
        raise ValueError("Official _sqlite3.pyd must dynamically import sqlite3.dll")
    native = root / "native"
    native.mkdir(exist_ok=True)
    arguments = command(sqlite_source, native, compiler)
    run(arguments, root)
    if any(digest(root / name) != expected for name, expected in inputs.items()):
        raise ValueError("Actual native build inputs changed during compilation")
    shutil.copytree(python_source, prefix)
    shutil.copy2(native / "sqlite3.dll", prefix / "DLLs/sqlite3.dll")
    result = qualify(python, root)
    manifest.write_text(json.dumps({"platform": platform.platform(), "runtime": result,
        "sources": [asdict(SQLITE), asdict(WINDOWS_PYTHON)], "defines": list(DEFINES),
        "native_inputs": inputs, "command": arguments, "binding_dependencies": dependencies,
        "tools": {name: {"path": path, "sha256": digest(Path(path))}
                  for name, path in (("cl", compiler), ("dumpbin", dumpbin))},
        "artifacts": artifacts(prefix)}, indent=2) + "\n", encoding="utf-8")
    return python


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/sqlite-runtime-windows-x64")
    parser.add_argument("--check-python", type=Path,
                        help="Check a package virtualenv against the prepared private runtime")
    args = parser.parse_args()
    if args.check_python:
        root = private_output(args.output)
        validate_saved(json.loads((root / "manifest.json").read_text(encoding="utf-8")), root)
        print(json.dumps(qualify(args.check_python.absolute(), root), indent=2))
    else:
        print(f"Runtime ready: {build(args.output)}")


if __name__ == "__main__":
    main()
