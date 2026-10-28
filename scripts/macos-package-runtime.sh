#!/usr/bin/env bash
# Shared private-runtime preparation for both native macOS package entrypoints.
# A cached candidate is reusable only after build_sqlite_runtime.py checks its
# pinned sources, installed artifact hashes and linked engine. No slow native
# build or frozen qualification is implied by the portable shell/mock tests.

macos_package_uv() {
  UV_PROJECT_ENVIRONMENT="$macos_package_environment" uv "$@"
}

prepare_macos_package_runtime() {
  local repository="$1"
  local runtime_root="$repository/build/sqlite-runtime-macos-arm64-py31316"
  local tool
  for tool in uv cc make ar perl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      echo "Native runtime preparation requires installed tool: $tool" >&2
      return 1
    fi
  done
  if [[ -f "$repository/build/sqlite-runtime-verified/manifest.json" ]]; then
    runtime_root="$repository/build/sqlite-runtime-verified"
  fi
  macos_package_environment="$repository/build/package-venv-macos-arm64"
  if [[ -L "$macos_package_environment" ]]; then
    echo "Private package environment must not be a symlink: $macos_package_environment" >&2
    return 1
  fi
  # qualification-tools provides Python 3.13 and uv, not a project environment.
  # Installed `uv help run`: --no-project skips project discovery; --isolated
  # also avoids a discovered/active .venv. No project sync or Python download.
  uv run --isolated --no-project --no-python-downloads --python 3.13 python \
    "$repository/scripts/build_sqlite_runtime.py" --output "$runtime_root" || return
  macos_package_uv sync --locked --python "$runtime_root/install/bin/python3.13" \
    --group package || return
  # Fail if uv reused an environment based on a different same-version Python.
  macos_package_uv run --no-sync python -I -B -c \
    'import pathlib, platform, sys; assert sys.platform == "darwin" and platform.machine() == "arm64"; assert sys.version_info[:3] == (3, 13, 16), sys.version; assert pathlib.Path(sys.base_prefix).resolve() == pathlib.Path(sys.argv[1]).resolve(), sys.base_prefix' \
    "$runtime_root/install" || return
  macos_package_uv run --no-sync python "$repository/scripts/check_sqlite_runtime.py"
}
