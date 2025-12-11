#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "[ffarm] Starting macOS install"

if ! xcode-select -p >/dev/null 2>&1; then
  echo "[ffarm] Installing Xcode Command Line Tools..."
  xcode-select --install || true
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "[ffarm] Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$HOME/.zprofile"
fi

BREW_BIN="$(command -v brew || true)"
if [ -z "$BREW_BIN" ] && [ -x /opt/homebrew/bin/brew ]; then
  BREW_BIN="/opt/homebrew/bin/brew"
elif [ -z "$BREW_BIN" ] && [ -x /usr/local/bin/brew ]; then
  BREW_BIN="/usr/local/bin/brew"
fi

if [ -z "$BREW_BIN" ]; then
  echo "[ffarm] ERROR: Unable to locate Homebrew after installation."
  exit 1
fi

eval "$("$BREW_BIN" shellenv)"

"$BREW_BIN" update

find_homebrew_python() {
  local formulas=("$@")
  for formula in "${formulas[@]}"; do
    local prefix
    prefix="$("$BREW_BIN" --prefix "$formula" 2>/dev/null || true)"
    if [ -z "$prefix" ]; then
      continue
    fi
    local candidates=(
      "$prefix/bin/python3"
      "$prefix/bin/python3."*
    )
    for candidate in "${candidates[@]}"; do
      if [ -x "$candidate" ]; then
        PYTHON_PREFIX="$prefix"
        PYTHON_BIN="$candidate"
        return 0
      fi
    done
  done
  return 1
}

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[ffarm] Installing FFmpeg..."
  "$BREW_BIN" install ffmpeg
fi

if ! "$BREW_BIN" ls --versions python@3 >/dev/null 2>&1; then
  echo "[ffarm] Installing Python 3 (Homebrew framework build)..."
  "$BREW_BIN" install python@3
fi

PYTHON_CANDIDATES=(
  python@3
  python3
  python
  python@3.14
  python@3.13
  python@3.12
)

if ! find_homebrew_python "${PYTHON_CANDIDATES[@]}"; then
  echo "[ffarm] ERROR: Unable to detect a functional Homebrew Python install (tried: ${PYTHON_CANDIDATES[*]})."
  echo "[ffarm] Try running: brew install python@3"
  exit 1
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
TK_FORMULA="python-tk@${PY_VERSION}"
TK_PREFIX=""

if "$BREW_BIN" ls --versions "$TK_FORMULA" >/dev/null 2>&1; then
  TK_PREFIX="$("$BREW_BIN" --prefix "$TK_FORMULA")"
else
  echo "[ffarm] Installing Tk bindings ($TK_FORMULA)..."
  if "$BREW_BIN" install "$TK_FORMULA"; then
    TK_PREFIX="$("$BREW_BIN" --prefix "$TK_FORMULA")"
  else
    echo "[ffarm] WARNING: $TK_FORMULA install failed. Falling back to Tcl/Tk framework."
  fi
fi

if [ -z "$TK_PREFIX" ]; then
  if ! "$BREW_BIN" ls --versions tcl-tk >/dev/null 2>&1; then
    echo "[ffarm] Installing Tcl/Tk..."
    "$BREW_BIN" install tcl-tk
  fi
  TK_PREFIX="$("$BREW_BIN" --prefix tcl-tk)"
fi

TK_SITE="$TK_PREFIX/lib/python$PY_VERSION/site-packages"
TK_DYNLOAD="$TK_PREFIX/lib/python$PY_VERSION/lib-dynload"

VENV_DIR="$ROOT_DIR/.venv"
VENV_CFG="$VENV_DIR/pyvenv.cfg"
DESIRED_HOME="$(dirname "$PYTHON_BIN")"

if [ -d "$VENV_DIR" ] && [ -f "$VENV_CFG" ]; then
  CURRENT_HOME="$(
    awk -F= '/^home/ {gsub(/^[[:space:]]+/, "", $2); gsub(/[[:space:]]+$/, "", $2); print $2}' "$VENV_CFG"
  )"
  if [ "$CURRENT_HOME" != "$DESIRED_HOME" ]; then
    if [[ "$CURRENT_HOME" == *"CommandLineTools"* ]]; then
      echo "[ffarm] Existing virtualenv uses Apple's Command Line Tools Python (no Tk GUI support). Recreating..."
    else
      echo "[ffarm] Existing virtualenv uses Python from $CURRENT_HOME (expected $DESIRED_HOME). Recreating..."
    fi
    rm -rf "$VENV_DIR"
  fi
elif [ -d "$VENV_DIR" ] && [ ! -f "$VENV_CFG" ]; then
  echo "[ffarm] Existing virtualenv is missing pyvenv.cfg; recreating with Homebrew Python..."
  rm -rf "$VENV_DIR"
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "[ffarm] Creating virtual environment with $PYTHON_BIN..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
  echo "[ffarm] ERROR: Virtualenv Python not found at $VENV_PYTHON."
  exit 1
fi

PYTHON_SITE_DIR="$VENV_DIR/lib/python$PY_VERSION/site-packages"

if [ -d "$PYTHON_SITE_DIR" ] && [ -d "$TK_SITE" ]; then
  PTH_FILE="$PYTHON_SITE_DIR/homebrew_tkinter.pth"
  {
    echo "$TK_SITE"
    if [ -d "$TK_DYNLOAD" ]; then
      echo "$TK_DYNLOAD"
    fi
  } > "$PTH_FILE"
fi

"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r requirements.txt

if ! "$VENV_PYTHON" - >/dev/null 2>&1 <<'PY'; then
import tkinter  # noqa: F401
PY
  echo "[ffarm] ERROR: Tkinter is still unavailable in this environment."
  echo "Check Homebrew permissions and ensure the python-tk formula installed correctly."
  exit 1
fi

echo "[ffarm] Install complete."
