"""Bounded ZIP validation, package identity and safe extraction."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
from stat import S_ISLNK
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from .policy import MAX_ARCHIVE, SCHEMA, TARGETS, canonical, require

AGENTS = {target: f"extension/bin/{target}/codex-usage-agent" + (".exe" if target == "win32-x64" else "")
    for target in TARGETS}


def zip_files(data):
    require(0 < len(data) <= MAX_ARCHIVE, "Archive size outside allowed bounds")
    with ZipFile(BytesIO(data)) as archive:
        entries = archive.infolist()
        require(len(entries) <= 20000 and sum(row.file_size for row in entries) <= MAX_ARCHIVE,
            "Expanded archive exceeds bounds")
        names = [row.filename for row in entries]
        require(len(names) == len(set(names)), "Duplicate ZIP paths")
        for row in entries:
            name = PurePosixPath(row.filename)
            require(not name.is_absolute() and ".." not in name.parts and "\\" not in row.filename
                and ":" not in row.filename and name.as_posix() == row.filename.rstrip("/")
                and not S_ISLNK(row.external_attr >> 16), "Unsafe ZIP entry")
        return {row.filename: archive.read(row) for row in entries if not row.is_dir()}


def file_identity(data):
    return {"sha256": sha256(data).hexdigest(), "bytes": len(data)}


def package_identity(data, target, version):
    require(target in TARGETS, "Unsupported package target")
    files = zip_files(data)
    require("extension/package.json" in files and "extension/out/extension.js" in files,
        "Incomplete extension assets")
    manifest = json.loads(files["extension/package.json"])
    require(manifest.get("publisher") == "wenjun-mao" and manifest.get("name") == "codex-usage-dashboard"
        and manifest.get("version") == version, "Package publisher/name/version mismatch")
    require("extension.vsixmanifest" in files, "Missing VSIX publication identity")
    xml = ElementTree.fromstring(files["extension.vsixmanifest"])
    identities = list(xml.iter("{http://schemas.microsoft.com/developer/vsx-schema/2011}Identity"))
    require(len(identities) == 1 and all(identities[0].get(key) == value for key, value in
        {"Id": "codex-usage-dashboard", "Version": version, "Publisher": "wenjun-mao", "TargetPlatform": target}.items()),
        "VSIX publication identity/target mismatch")
    collectors = {name for name in files if name.startswith("extension/bin/")}
    require(collectors == {AGENTS[target]}, "Foreign or missing collector")
    require(not any("src-tauri/" in name or name.startswith("extension/apps/desktop/") for name in files),
        "Native app files are not a companion release")
    assets = {name: file_identity(value) for name, value in sorted(files.items()) if name.startswith("extension/")}
    return {**file_identity(data), "target": target, "version": version,
        "collector_sha256": assets[AGENTS[target]]["sha256"], "assets": assets}


def make_payload(directory, output, gate, source, *, target=None, version=None):
    directory, output = Path(directory), Path(output)
    candidates = [file for file in directory.rglob("*") if file.is_file()
        and file.suffix in (".json", ".png", ".xml", ".vsix")]
    require(not any(file.is_symlink() for file in candidates), "Symlink is not qualification evidence")
    files = {str(file.relative_to(directory)).replace("\\", "/"): file.read_bytes() for file in candidates}
    require(files and sum(map(len, files.values())) <= MAX_ARCHIVE, "Empty or oversized qualification payload")
    metadata = {"schema": SCHEMA, "gate": gate, "source": source,
        "files": {name: file_identity(data) for name, data in sorted(files.items())}}
    if target:
        names = [name for name in files if name.endswith(".vsix")]
        require(len(names) == 1, "Expected exactly one platform package")
        metadata["package_file"] = names[0]
        metadata["package"] = package_identity(files[names[0]], target, version)
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=1) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
        archive.writestr("payload.json", canonical(metadata))
    return metadata


def inspect_payload(data, gate, source):
    files = zip_files(data)
    require("payload.json" in files, "Missing payload manifest")
    metadata = json.loads(files.pop("payload.json"))
    require(type(metadata.get("schema")) is int and metadata["schema"] == SCHEMA and metadata.get("gate") == gate
        and metadata.get("source") == source, "Foreign payload manifest")
    require(metadata.get("files") == {name: file_identity(value) for name, value in sorted(files.items())},
        "Payload file inventory/hash mismatch")
    if gate.startswith("package-"):
        name = metadata.get("package_file")
        require(name in files, "Missing qualified package")
        require(metadata.get("package") == package_identity(files[name], gate.removeprefix("package-"), source["version"]),
            "Qualified package identity mismatch")
    return metadata, files


def extract_extension(data, destination, version):
    identity = package_identity(data, "darwin-arm64", version)
    destination = Path(destination)
    require(not destination.exists(), "Native extension destination must be fresh")
    destination.mkdir()
    for name, content in zip_files(data).items():
        if name.startswith("extension/"):
            target = destination / name.removeprefix("extension/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    (destination / AGENTS["darwin-arm64"].removeprefix("extension/")).chmod(0o755)
    return identity
