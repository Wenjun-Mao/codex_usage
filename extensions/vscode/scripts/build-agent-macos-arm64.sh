#!/usr/bin/env bash
set -euo pipefail

extension_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repository_root="$(cd "$extension_root/../.." && pwd)"
source_binary="$repository_root/apps/desktop/src-tauri/binaries/codex-usage-agent-aarch64-apple-darwin"
target_binary="$extension_root/bin/darwin-arm64/codex-usage-agent"

bash "$repository_root/scripts/build-agent-macos-arm64.sh"
test -f "$source_binary"
rm -f "$extension_root/bin/win32-x64/codex-usage-agent.exe"
mkdir -p "$(dirname "$target_binary")"
cp "$source_binary" "$target_binary"
chmod +x "$target_binary"
