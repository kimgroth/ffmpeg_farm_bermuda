#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "[ffarm] Removing virtual environment..."
rm -rf "$ROOT_DIR/.venv"

echo "[ffarm] Uninstall complete. Homebrew packages were left intact."
