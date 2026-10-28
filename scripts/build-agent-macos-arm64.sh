#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/scripts/macos-package-runtime.sh"
target_triple="aarch64-apple-darwin"
binary_name="codex-usage-agent-$target_triple"
dist_dir="$repo_root/build/packaged-agent/$target_triple"
work_dir="$repo_root/build/pyinstaller-agent-$target_triple"
entry_point="$repo_root/src/codex_usage/agent_main.py"
binary_path="$dist_dir/$binary_name"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "This script must run on macOS Apple Silicon." >&2
  exit 2
fi

cd "$repo_root"
prepare_macos_package_runtime "$repo_root"
mkdir -p "$dist_dir" "$work_dir"
rm -f "$binary_path"
macos_package_uv run --no-sync pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --console \
  --name "$binary_name" \
  --paths src \
  --distpath "$dist_dir" \
  --workpath "$work_dir" \
  --specpath "$work_dir" \
  "$entry_point"


chmod +x "$binary_path"
"$binary_path" --help >/dev/null
macos_package_uv run --no-sync python scripts/verify_packaged_sqlite.py --executable "$binary_path" \
  --output output/qualification/package-darwin-arm64/sqlite-runtime.json
macos_package_uv run --no-sync python scripts/smoke-test-packaged-agent.py --executable "$binary_path" \
  --parallel-evidence output/qualification/package-darwin-arm64/collector-parallel.json \
  --wal-evidence output/qualification/package-darwin-arm64/sqlite-maintenance.json
