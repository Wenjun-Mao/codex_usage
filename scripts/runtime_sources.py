"""Pinned, unmodified upstream inputs for the isolated SQLite runtime build."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import tarfile
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from uuid import uuid4
import zipfile


@dataclass(frozen=True)
class Source:
    url: str
    algorithm: str
    checksum: str
    directory: str


SQLITE = Source(
    "https://www.sqlite.org/2026/sqlite-amalgamation-3540100.zip", "sha3_256",
    "92281c86e2957f9b9305890f9ac04204caa7b677cc868dc326d942689df28e30",
    "sqlite-amalgamation-3540100",
)
PYTHON = Source(
    "https://www.python.org/ftp/python/3.13.16/Python-3.13.16.tgz", "sha256",
    "cfac63bddf956deafb1172ca131ae5dcaafd6f95056086e233fca205593ed427", "Python-3.13.16",
)
OPENSSL = Source(
    "https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz", "sha256",
    "603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a", "openssl-3.5.9",
)


def prepare(source: Source, root: Path) -> Path:
    downloads = root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / source.url.rsplit("/", 1)[1]
    if not archive.exists():
        partial = archive.with_suffix(archive.suffix + ".part")
        try:
            with urlopen(source.url, timeout=60) as response, partial.open("wb") as destination:
                shutil.copyfileobj(response, destination)
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    verify_archive(source, root)
    sources = root / "sources"
    sources.mkdir(exist_ok=True)
    target = sources / f"{source.directory}-{uuid4().hex}"
    with TemporaryDirectory(prefix='extract-', dir=sources) as raw:
        staging = Path(raw)
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as bundle:
                for item in bundle.infolist():
                    relative = Path(item.filename)
                    if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != source.directory:
                        raise ValueError("Unsafe upstream ZIP member")
                    if (item.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError("Upstream ZIP contains a symlink")
                bundle.extractall(staging)
        else:
            with tarfile.open(archive) as bundle:
                if any(Path(item.name).parts[0] != source.directory for item in bundle.getmembers()):
                    raise ValueError("Unexpected upstream TAR root")
                bundle.extractall(staging, filter="data")
        (staging / source.directory).replace(target)
    return target


def verify_archive(source: Source, root: Path):
    archive = root / "downloads" / source.url.rsplit("/", 1)[1]
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, source.algorithm).hexdigest()
    if actual != source.checksum:
        raise ValueError(f"Upstream archive checksum mismatch: {archive.name}")
