#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

"$SCRIPT_DIR/install_ubuntu.sh"

VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
  echo "[ffarm] ERROR: Expected virtualenv Python at $VENV_PYTHON but it was not found."
  exit 1
fi

cd "$PROJECT_DIR"
exec "$VENV_PYTHON" -m ffarm master --host 0.0.0.0 --port 8000
