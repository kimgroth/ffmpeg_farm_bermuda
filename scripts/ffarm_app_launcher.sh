#!/usr/bin/env bash
set -euo pipefail

APP_SUPPORT="$HOME/Library/Application Support/FFarm"
REPO_DIR="$APP_SUPPORT/ffmpeg_farm_bermuda"
LOG_DIR="$HOME/Library/Logs/FFarm"
LOG_FILE="$LOG_DIR/ffarm.log"

set +e
mkdir -p "$LOG_DIR"
touch "$LOG_FILE"
if [ ! -w "$LOG_FILE" ]; then
  LOG_DIR="/tmp/ffarm"
  LOG_FILE="$LOG_DIR/ffarm.log"
  mkdir -p "$LOG_DIR"
  touch "$LOG_FILE"
fi
{
  echo ""
  echo "----- FFarm launch $(date) -----"
} >> "$LOG_FILE"
exec >> "$LOG_FILE" 2>&1
set -e

notify() {
  local message="$1"
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"$message\" with title \"FFarm\"" >/dev/null 2>&1 || true
  fi
}

mkdir -p "$APP_SUPPORT"

if [ ! -d "$REPO_DIR/.git" ]; then
  if ! command -v git >/dev/null 2>&1; then
    echo "[ffarm] ERROR: git is required to install FFarm."
    exit 1
  fi
  notify "First-time setup: downloading FFarm..."
  echo "[ffarm] Cloning FFarm repo..."
  git clone https://github.com/kimgroth/ffmpeg_farm_bermuda "$REPO_DIR"
fi

if [ ! -x "$REPO_DIR/.venv/bin/python" ]; then
  if ! command -v brew >/dev/null 2>&1; then
    notify "FFarm needs Homebrew. A Terminal window will open to install it."
    if command -v osascript >/dev/null 2>&1; then
      osascript <<OSA
tell application "Terminal"
  activate
  do script "bash \"$REPO_DIR/scripts/install_macos.sh\""
end tell
OSA
    fi
    echo "[ffarm] Homebrew missing; launched installer in Terminal."
    exit 0
  fi
  notify "Installing FFarm dependencies (this may take a few minutes)..."
  echo "[ffarm] Installing dependencies..."
  "$REPO_DIR/scripts/install_macos.sh"
fi

cd "$REPO_DIR"
export PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$REPO_DIR/.venv/bin/python" -m ffarm master
