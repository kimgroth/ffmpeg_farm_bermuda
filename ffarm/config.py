"""
Application-wide configuration defaults.
"""

from __future__ import annotations

from pathlib import Path

APP_NAME = "LAN FFmpeg Farm"
SERVICE_TYPE = "_ffarm._tcp.local."
MASTER_SERVICE_TYPE = "_ffarm-master._tcp.local."
DEFAULT_DB_PATH = Path.home() / ".ffarm" / "ffarm.sqlite3"
LEASE_DURATION_SECONDS = 15 * 60
HEARTBEAT_TIMEOUT_SECONDS = 30
FFMPEG_PROGRESS_POLL_INTERVAL = 2.0
WORKER_POLL_INTERVAL = 5.0
GUI_REFRESH_INTERVAL_MS = 1_000
