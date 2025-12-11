"""
Worker client that communicates with the master and executes FFmpeg jobs.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from zeroconf import ServiceInfo, Zeroconf

from ..config import SERVICE_TYPE, WORKER_POLL_INTERVAL
from ..master_discovery import discover_master
from ..models import CompletionReport, LeaseResponse, WorkerStatus
from ..profiles import build_profile_command

log = logging.getLogger(__name__)


PROGRESS_PATTERN = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
FFPROBE_ARGS = [
    "-v",
    "error",
    "-show_entries",
    "format=duration",
    "-of",
    "default=noprint_wrappers=1:nokey=1",
]


def _seconds_from_match(match: re.Match[str]) -> float:
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _get_default_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


@dataclass
class ActiveJob:
    job_id: int
    input_path: str
    output_path: str
    profile: str
    ffmpeg_args: list[str]

COMMON_FFMPEG_PATHS = ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]
COMMON_FFPROBE_PATHS = ["/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe", "/usr/bin/ffprobe"]


class WorkerClient:
    def __init__(
        self,
        master_url: Optional[str] = None,
        *,
        worker_id: Optional[str] = None,
        name: Optional[str] = None,
        advertise: bool = True,
    ):
        self.master_url = self._resolve_master(master_url)
        self.worker_id = worker_id or str(uuid.uuid4())
        self.name = name or f"Worker-{socket.gethostname()}"
        self.advertise = advertise
        self.client = httpx.Client(base_url=self.master_url, timeout=15.0)
        self._stop_event = threading.Event()
        self._force_stop_event = threading.Event()
        self._current_job: Optional[ActiveJob] = None
        self._last_lease_response: Optional[LeaseResponse] = None
        self._zeroconf: Optional[Zeroconf] = None
        self._service_info: Optional[ServiceInfo] = None
        self._lock = threading.Lock()
        self._last_stdout: deque[str] = deque(maxlen=50)
        self._last_stderr: deque[str] = deque(maxlen=50)
        self._status = WorkerStatus.ONLINE
        self._accept_leases = True
        self._heartbeat_interval = 10.0
        self._heartbeat_thread: threading.Thread | None = None
        self._active_process: Optional[subprocess.Popen[str]] = None
        self._ffmpeg_bin = self._resolve_tool("FFARM_FFMPEG", "ffmpeg", COMMON_FFMPEG_PATHS)
        self._ffprobe_bin = self._resolve_tool("FFARM_FFPROBE", "ffprobe", COMMON_FFPROBE_PATHS)

    def _resolve_master(self, override: Optional[str]) -> str:
        candidates = [
            override,
            os.environ.get("FFARM_MASTER_URL"),
        ]
        for candidate in candidates:
            if candidate:
                return candidate.rstrip("/")
        discovered = discover_master()
        if discovered:
            return discovered.rstrip("/")
        raise RuntimeError(
            "Unable to locate master server automatically. "
            "Set FFARM_MASTER_URL or provide --master."
        )

    def run(self):
        try:
            if self.advertise:
                self._start_advertising()
            self._start_heartbeat()
            self._loop()
        finally:
            self._cleanup()

    def stop(self):
        self._stop_event.set()
        self._force_stop_event.set()
        self._terminate_active_process()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2.0)

    def _loop(self):
        while not self._stop_event.is_set():
            if self._current_job is None and self._accept_leases and not self._force_stop_event.is_set():
                lease = self._request_job()
                if lease:
                    self._execute_job(lease)
                    continue
            time.sleep(WORKER_POLL_INTERVAL)

    def _request_job(self) -> Optional[ActiveJob]:
        try:
            response = self.client.post(
                "/api/v1/jobs/lease",
                json={
                    "worker_id": self.worker_id,
                    "name": self.name,
                    "base_url": "",  # reserved for future use
                },
            )
        except httpx.RequestError as exc:
            log.error("Lease request failed: %s", exc)
            return None

        if response.status_code != 200:
            log.error("Lease request returned %s", response.status_code)
            return None

        payload = LeaseResponse.parse_obj(response.json())
        self._last_lease_response = payload
        if payload.action == "force_stop":
            self._status = WorkerStatus.FORCE_STOPPING
            self._force_stop_event.set()
            return None
        if payload.action == "stop":
            self._status = WorkerStatus.STOPPING
            self._accept_leases = False
            return None
        if not payload.job_id:
            self._accept_leases = payload.accept_leases
            return None
        self._accept_leases = payload.accept_leases
        return ActiveJob(
            job_id=payload.job_id,
            input_path=payload.input_path,
            output_path=payload.output_path,
            profile=payload.profile,
            ffmpeg_args=payload.ffmpeg_args,
        )

    def _send_heartbeat(self):
        payload = {
            "worker_id": self.worker_id,
            "name": self.name,
            "base_url": "",
            "running_job_id": self._current_job.job_id if self._current_job else None,
            "status": self._status,
        }
        try:
            response = self.client.post("/api/v1/workers/heartbeat", json=payload)
            response.raise_for_status()
            data = response.json()
            self._accept_leases = data.get("accept_leases", True)
            status = data.get("status", WorkerStatus.ONLINE)
            if status == WorkerStatus.FORCE_STOPPING:
                self._status = WorkerStatus.FORCE_STOPPING
                self._force_stop_event.set()
            elif status == WorkerStatus.STOPPING:
                self._status = WorkerStatus.STOPPING
                self._accept_leases = False
            else:
                if self._current_job is None:
                    self._status = WorkerStatus.ONLINE
        except httpx.RequestError as exc:
            log.error("Heartbeat failed: %s", exc)

    def _execute_job(self, job: ActiveJob):
        self._current_job = job
        self._status = WorkerStatus.ONLINE
        self._last_stdout.clear()
        self._last_stderr.clear()
        duration = self._probe_duration(job.input_path)
        progress = 0.0

        ffmpeg_bin = self._ffmpeg_bin or self._resolve_tool("FFARM_FFMPEG", "ffmpeg", COMMON_FFMPEG_PATHS)
        if not ffmpeg_bin:
            log.error("FFmpeg executable not found; set FFARM_FFMPEG or add ffmpeg to PATH")
            self._send_completion(job.job_id, False, return_code=-1)
            self._current_job = None
            return

        ffmpeg_args = [ffmpeg_bin] + list(job.ffmpeg_args)
        Path(job.output_path).parent.mkdir(parents=True, exist_ok=True)
        log.info("Starting job %s", job.job_id)

        try:
            process = subprocess.Popen(
                ffmpeg_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            log.exception("FFmpeg executable not found")
            self._send_completion(job.job_id, False, return_code=-1)
            self._current_job = None
            return
        except OSError:
            log.exception("Failed to start FFmpeg")
            self._send_completion(job.job_id, False, return_code=-1)
            self._current_job = None
            return

        self._active_process = process
        force_thread = threading.Thread(
            target=self._watch_force_stop,
            args=(process,),
            daemon=True,
            name="ffarm-force-stop",
        )
        force_thread.start()

        progress_thread = None
        if process.stdout:
            progress_thread = threading.Thread(
                target=self._progress_reader,
                args=(process.stdout, job.job_id, duration),
                daemon=True,
                name="ffarm-progress",
            )
            progress_thread.start()
        self._send_progress(job.job_id, progress)

        try:
            if process.stderr:
                for line in iter(process.stderr.readline, ""):
                    if self._force_stop_event.is_set():
                        process.terminate()
                        break
                    line = line.rstrip()
                    if not line:
                        continue
                    self._last_stderr.append(line)
                    match = PROGRESS_PATTERN.search(line)
                    if match and duration:
                        seconds = _seconds_from_match(match)
                        progress = min(0.99, seconds / duration)
                    self._send_progress(job.job_id, progress)
        finally:
            if process.stderr:
                process.stderr.close()

        return_code = process.wait()
        if progress_thread and progress_thread.is_alive():
            progress_thread.join(timeout=0.5)
        self._active_process = None
        success = return_code == 0 and not self._force_stop_event.is_set()
        if self._force_stop_event.is_set() and return_code != 0:
            success = False
            self._status = WorkerStatus.FORCE_STOPPING
        self._send_completion(job.job_id, success, return_code)
        self._current_job = None
        self._force_stop_event.clear()
        self._status = WorkerStatus.STOPPED if not self._accept_leases else WorkerStatus.ONLINE
        log.info("Job %s finished with code %s", job.job_id, return_code)

    def _send_progress(self, job_id: int, progress: float):
        payload = {
            "worker_id": self.worker_id,
            "progress": progress,
            "stderr_tail": "\n".join(list(self._last_stderr)[-10:]) if self._last_stderr else None,
            "stdout_tail": "\n".join(list(self._last_stdout)[-10:]) if self._last_stdout else None,
        }
        try:
            self.client.post(f"/api/v1/jobs/{job_id}/progress", json=payload)
        except httpx.RequestError:
            log.exception("Failed to send progress update")

    def _send_completion(self, job_id: int, success: bool, return_code: int):
        payload = {
            "worker_id": self.worker_id,
            "success": success,
            "return_code": return_code,
            "stderr_tail": "\n".join(self._last_stderr),
            "stdout_tail": "\n".join(self._last_stdout),
            "error_message": None if success else "FFmpeg failed",
        }
        try:
            self.client.post(f"/api/v1/jobs/{job_id}/complete", json=payload)
        except httpx.RequestError:
            log.exception("Failed to send completion report")

    def _progress_reader(self, stream, job_id: int, duration: Optional[float]):
        if stream is None:
            return
        try:
            for raw_line in iter(stream.readline, ""):
                line = raw_line.strip()
                if not line:
                    continue
                self._last_stdout.append(line)
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key == "out_time_ms":
                    try:
                        seconds = int(value) / 1_000_000.0
                    except (TypeError, ValueError):
                        continue
                    if duration:
                        progress = min(0.999, seconds / duration)
                        self._send_progress(job_id, progress)
                elif key == "out_time":
                    seconds = self._parse_timestamp(value)
                    if seconds is not None and duration:
                        progress = min(0.999, seconds / duration)
                        self._send_progress(job_id, progress)
                elif key == "progress" and value == "end":
                    self._send_progress(job_id, 1.0)
        finally:
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _parse_timestamp(value: str | None) -> Optional[float]:
        if not value:
            return None
        parts = value.split(":")
        if len(parts) != 3:
            return None
        try:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
        except ValueError:
            return None
        return hours * 3600 + minutes * 60 + seconds

    def _watch_force_stop(self, process: subprocess.Popen[str]):
        while process.poll() is None and not self._stop_event.is_set():
            if self._force_stop_event.wait(0.5):
                self._terminate_process(process)
                return

    def _terminate_active_process(self):
        process = self._active_process
        if process is None:
            return
        self._terminate_process(process)

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]):
        if process.poll() is not None:
            return
        try:
            process.terminate()
        except OSError:
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass

    def _probe_duration(self, input_path: str) -> Optional[float]:
        ffprobe_bin = self._ffprobe_bin or self._resolve_tool("FFARM_FFPROBE", "ffprobe", COMMON_FFPROBE_PATHS)
        if not ffprobe_bin:
            log.warning("FFprobe executable not found; duration tracking disabled")
            return None
        cmd = [ffprobe_bin] + FFPROBE_ARGS + [input_path]
        try:
            result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            duration_str = result.stdout.strip()
            if duration_str:
                return float(duration_str)
        except (subprocess.CalledProcessError, ValueError):
            log.warning("Failed to determine duration for %s", input_path)
        return None

    def _start_advertising(self):
        self._zeroconf = Zeroconf()
        ip = _get_default_ip()
        info = ServiceInfo(
            type_=SERVICE_TYPE,
            name=f"{self.worker_id}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(ip)],
            port=0,
            properties={
                b"id": self.worker_id.encode(),
                b"name": self.name.encode(),
                b"base_url": b"",
            },
        )
        self._service_info = info
        self._zeroconf.register_service(info)

    def _cleanup(self):
        self._terminate_active_process()
        if self.client:
            self.client.close()
        if self._zeroconf and self._service_info:
            try:
                self._zeroconf.unregister_service(self._service_info)
            except Exception:  # noqa: BLE001
                pass
            finally:
                self._zeroconf.close()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._stop_event.set()
            self._heartbeat_thread.join(timeout=2.0)

    @staticmethod
    def _resolve_tool(env_var: str, executable: str, fallbacks: list[str] | tuple[str, ...] = ()) -> Optional[str]:
        override = os.environ.get(env_var)
        if override:
            if os.path.isabs(override) and os.access(override, os.X_OK):
                return override
            resolved = shutil.which(override)
            if resolved:
                return resolved
            log.warning("%s=%s is not executable", env_var, override)
        resolved = shutil.which(executable)
        if resolved:
            return resolved
        for candidate in fallbacks:
            if candidate and os.path.isabs(candidate) and os.access(candidate, os.X_OK):
                return candidate
        log.warning("Executable '%s' not found on PATH (checked %s)", executable, ", ".join(fallbacks))
        return None

    def _start_heartbeat(self):
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name="ffarm-heartbeat")
        self._heartbeat_thread.start()

    def _heartbeat_loop(self):
        # Send an immediate heartbeat so master sees us right away.
        self._send_heartbeat()
        while not self._stop_event.wait(self._heartbeat_interval):
            self._send_heartbeat()
