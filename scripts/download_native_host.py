"""Download one hash-pinned VS Code host into an isolated macOS runner directory."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
from urllib.request import urlopen

from release.native import host_identity
from release.policy import HOST, canonical, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(platform.system() == "Darwin" and platform.machine() == "arm64", "Host requires macOS ARM64")
    require(not args.output.exists(), "Native host directory must be fresh")
    args.output.mkdir(parents=True)
    archive = args.output / "host.zip"
    digest = sha256()
    total = 0
    with urlopen(HOST["url"], timeout=90) as response, archive.open("wb") as output:
        require(response.url == HOST["url"], "Unexpected pinned host redirect")
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            require(total <= 500 * 1024 * 1024, "Native host download exceeds bounds")
            digest.update(chunk)
            output.write(chunk)
    require(digest.hexdigest() == HOST["sha256"], "Pinned VS Code archive mismatch")
    subprocess.run(["ditto", "-x", "-k", str(archive), str(args.output)], check=True)
    code = args.output / "Visual Studio Code.app/Contents/MacOS/Code"
    host = host_identity(code)
    require(host["version"] == HOST["version"] and host["commit"] == HOST["commit"], "Pinned host metadata mismatch")
    (args.output / "host.json").write_bytes(canonical({**HOST, **host, "archive_bytes": total}))
    print(json.dumps({"code": str(code), "version": host["version"], "commit": host["commit"]}))


if __name__ == "__main__":
    main()
