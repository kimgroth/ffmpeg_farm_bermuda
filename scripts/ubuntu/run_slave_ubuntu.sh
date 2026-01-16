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
MASTER_URL="${FFARM_MASTER_URL:-}"
CMD=("$VENV_PYTHON" "-m" "ffarm" "worker")
if [ -n "$MASTER_URL" ]; then
  CMD+=("--master" "$MASTER_URL")
fi
exec "${CMD[@]}"
