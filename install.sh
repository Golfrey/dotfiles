#!/bin/sh

set -eu

if command -v chezmoi >/dev/null 2>&1; then
  chezmoi=chezmoi
else
  bin_dir="$HOME/.local/bin"
  chezmoi="$bin_dir/chezmoi"
  mkdir -p "$bin_dir"

  if command -v curl >/dev/null 2>&1; then
    sh -c "$(curl -fsLS https://get.chezmoi.io)" -- -b "$bin_dir"
  elif command -v wget >/dev/null 2>&1; then
    sh -c "$(wget -qO- https://get.chezmoi.io)" -- -b "$bin_dir"
  else
    echo "To install chezmoi, you must have curl or wget installed." >&2
    exit 1
  fi
fi

# POSIX way to get this script's directory.
script_dir="$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd -P)"

if [ -n "${CHEZMOI_PROFILE:-}" ]; then
  exec "$chezmoi" init "--source=$script_dir" --promptChoice "profile=$CHEZMOI_PROFILE" "$@"
fi

exec "$chezmoi" init "--source=$script_dir" "$@"
