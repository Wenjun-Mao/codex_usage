#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target_triple="aarch64-apple-darwin"
binary_name="codex-usage-agent-$target_triple"
dist_dir="$repo_root/apps/desktop/src-tauri/binaries"
work_dir="$repo_root/build/pyinstaller-agent-$target_triple"
entry_point="$repo_root/src/codex_usage/agent_main.py"
binary_path="$dist_dir/$binary_name"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "This script must run on macOS Apple Silicon." >&2
  exit 2
fi

mkdir -p "$dist_dir" "$work_dir"
rm -f "$binary_path"

cd "$repo_root"
uv run --group package pyinstaller \
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
uv run python scripts/smoke-test-packaged-agent.py --executable "$binary_path"
