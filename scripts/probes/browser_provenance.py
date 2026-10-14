"""Post-replay identity of configured WebKit binaries; never timed DOM work."""
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path


def file_digest(path):
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def binary_inventory(executable):
    executable = Path(executable)
    root = next((p for p in executable.parents if p.name.startswith("webkit-")), None)
    if root is None or not root.is_dir() or not executable.is_file():
        return {"configured_executable": str(executable), "status": "unavailable"}
    files = {p.relative_to(root).as_posix(): file_digest(p) for p in sorted(root.rglob("*"))
        if p.is_file() and not p.is_symlink()}
    links = {p.relative_to(root).as_posix(): os.readlink(p) for p in sorted(root.rglob("*")) if p.is_symlink()}
    return {"configured_executable": str(executable), "root": str(root), "status": "captured",
        "files": files, "symlinks": links,
        "tree_sha256": sha256(json.dumps({"files": files, "symlinks": links}, sort_keys=True).encode()).hexdigest()}


def collect(browsers):
    import playwright
    manifest = Path(playwright.__file__).parent / "driver/package/browsers.json"
    result = {"sdk_version": version("playwright"), "sdk_browsers": json.loads(manifest.read_bytes()),
        "browsers": browsers.copy(), "webkit_binary_inventory": None}
    if "webkit" in browsers:
        result["webkit_binary_inventory"] = binary_inventory(browsers["webkit"]["configured_executable"])
    return result
