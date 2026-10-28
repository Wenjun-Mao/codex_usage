"""Official CPython Windows build distribution, without running an installer.

CPython documents NuGet packages for build environments:
https://docs.python.org/3.13/using/windows.html#the-nuget-org-packages
Unlike PBS, this pinned package has a separate _sqlite3.pyd/sqlite3.dll pair.
The archive digest below was measured from the PSF's versioned NuGet artifact.
"""
import hashlib
from pathlib import Path, PurePosixPath
import shutil
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from uuid import uuid4
import zipfile

from runtime_sources import Source


WINDOWS_PYTHON = Source(
    "https://api.nuget.org/v3-flatcontainer/python/3.13.16/python.3.13.16.nupkg",
    "sha256", "95fad176338f1d6a799e45946488063f4aa61764e6cff2f132ddeffbf7a04c34", "tools",
)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_python(root, source=WINDOWS_PYTHON):
    """Verify the entire NuGet archive, publish a fresh tools tree atomically."""
    downloads = root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / source.url.rsplit("/", 1)[1]
    if not archive.exists():
        partial = archive.with_suffix(".part")
        try:
            with urlopen(source.url, timeout=60) as response, partial.open("wb") as output:
                shutil.copyfileobj(response, output)
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    if digest(archive) != source.checksum:
        raise ValueError("Windows CPython archive checksum mismatch")
    sources = root / "sources"
    sources.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="nuget-", dir=sources) as raw:
        staging = Path(raw)
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                relative = PurePosixPath(item.filename)
                # Also reject Windows drive names, ADS and backslash traversal on POSIX.
                if (relative.is_absolute() or ".." in relative.parts
                        or ":" in item.filename or "\\" in item.filename
                        or (item.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError("Unsafe NuGet ZIP member")
                if relative.parts and relative.parts[0] == source.directory:
                    bundle.extract(item, staging)
        target = sources / f"windows-python-{uuid4().hex}"
        (staging / source.directory).replace(target)
    return target
