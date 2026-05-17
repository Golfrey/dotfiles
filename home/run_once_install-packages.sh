#!/bin/sh
set -eu

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is not installed; skipping brew bundle."
  echo "Install Homebrew, then run: brew bundle --global"
  exit 0
fi

echo "Installing Homebrew packages from ~/.Brewfile..."
brew bundle --global
