"""Foreground synthetic tunnel launcher; credentials never enter CLI arguments."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parents[1] / "output" / "openai-plugin"
DEFAULT_CLIENT = OUTPUT / "tunnel-client" / "v0.0.15" / "tunnel-client"
PROFILE_DIR = OUTPUT / "profiles"
PROFILE = "codex-usage-synthetic"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "doctor", "run"])
    parser.add_argument("--client", type=Path, default=DEFAULT_CLIENT)
    args = parser.parse_args()
    config_file = ROOT / ".env"
    if os.name == "posix" and config_file.exists() and config_file.stat().st_mode & 0o077:
        parser.error("Restrict the local credential file first: chmod 600 .env")
    config = dotenv_values(config_file, interpolate=False)
    tunnel_id = config.get("CODEX_USAGE_TUNNEL_ID")
    if not tunnel_id or not tunnel_id.startswith("tunnel_"):
        parser.error("Configure CODEX_USAGE_TUNNEL_ID in the local .env file.")
    if not args.client.is_file():
        parser.error("Install the official tunnel client or supply --client.")
    command = [str(args.client), args.action, "--profile-dir", str(PROFILE_DIR),
               "--profile", PROFILE]
    # Do not inherit unrelated tunnel profiles, Harpoon targets, or debug options.
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG")
           if key in os.environ}
    if args.action == "init":
        uv = shutil.which("uv")
        if not uv:
            parser.error("uv is required to launch the isolated probe.")
        mcp_command = shlex.join([
            uv, "--directory", str(ROOT), "run", "--frozen", "python",
            "-m", "probe.server",
        ])
        command += ["--sample", "sample_mcp_stdio_local", "--tunnel-id", tunnel_id,
                    "--mcp-command", mcp_command, "--health-listen-addr", "127.0.0.1:0"]
        sys.exit(subprocess.call(command, env=env))
    key = config.get("CONTROL_PLANE_API_KEY")
    if not key:
        parser.error("Enter CONTROL_PLANE_API_KEY locally; do not paste it into chat.")
    env["CONTROL_PLANE_API_KEY"] = key
    command += ["--control-plane.tunnel-id", tunnel_id]
    if args.action == "doctor":
        command += ["--explain"]
    else:
        command += ["--health.url-file", str(OUTPUT / "health.url")]
    os.execve(str(args.client), command, env)


if __name__ == "__main__":
    main()
