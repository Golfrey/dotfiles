#!/bin/sh
set -eu

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is not installed; skipping brew bundle."
  echo "Install Homebrew, then run: HOMEBREW_NO_AUTO_UPDATE=1 brew bundle --global --no-upgrade --jobs=auto"
  exit 0
fi

echo "Installing Homebrew packages from ~/.Brewfile..."
# HOMEBREW_NO_AUTO_UPDATE avoids a slow auto-update during server bootstrap.
# --no-upgrade avoids upgrading existing packages, which can make server setup take forever.
# --jobs=auto allows Homebrew Bundle to install independent formulae in parallel.
: "${HOMEBREW_NO_AUTO_UPDATE:=1}"
export HOMEBREW_NO_AUTO_UPDATE
brew bundle --global --no-upgrade --jobs=auto
