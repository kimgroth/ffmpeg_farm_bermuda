#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

"$SCRIPT_DIR/install_macos.sh"

if command -v brew >/dev/null 2>&1; then
  eval "$(brew shellenv)"
elif [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
  echo "[ffarm] ERROR: Expected virtualenv Python at $VENV_PYTHON but it was not found."
  exit 1
fi

cd "$PROJECT_DIR"
exec "$VENV_PYTHON" -m ffarm master --host 0.0.0.0 --port 8000
