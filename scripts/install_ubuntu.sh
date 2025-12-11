#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "[ffarm] Installing dependencies via apt"
sudo apt-get update
sudo apt-get install -y ffmpeg python3 python3-venv python3-pip python3-tk build-essential curl

if [ ! -d "$ROOT_DIR/.venv" ]; then
  python3 -m venv "$ROOT_DIR/.venv"
fi

source "$ROOT_DIR/.venv/bin/activate"
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "[ffarm] Install complete."
