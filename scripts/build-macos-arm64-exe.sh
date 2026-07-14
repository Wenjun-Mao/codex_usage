#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dist_dir="$repo_root/extensions/vscode/bin/darwin-arm64"
work_dir="$repo_root/build/pyinstaller-darwin-arm64"
entry_point="$repo_root/src/codex_usage/__main__.py"
exe_path="$dist_dir/codex-usage"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "This script must run on macOS Apple Silicon (darwin-arm64)." >&2
  exit 2
fi

mkdir -p "$dist_dir" "$work_dir"
rm -f "$exe_path"

cd "$repo_root"
uv run --group package pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --console \
  --name codex-usage \
  --paths src \
  --distpath "$dist_dir" \
  --workpath "$work_dir" \
  --specpath "$work_dir" \
  "$entry_point"

if [[ ! -f "$exe_path" ]]; then
  echo "Expected executable was not created: $exe_path" >&2
  exit 1
fi

chmod +x "$exe_path"
"$exe_path" --help >/dev/null
uv run python "$repo_root/scripts/smoke-test-packaged-sync.py" --executable "$exe_path"
