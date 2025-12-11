"""
Zeroconf (mDNS) discovery utilities.
"""

from __future__ import annotations

import logging
import socket
import threading
from typing import Optional

from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

from .config import SERVICE_TYPE
from .workers import upsert_worker

log = logging.getLogger(__name__)


class WorkerServiceListener(ServiceListener):
    """
    Captures worker broadcast events and persists their metadata.
    """

    def add_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        info = zeroconf.get_service_info(type_, name)
        if info:
            self._sync_worker(info)

    def update_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        info = zeroconf.get_service_info(type_, name)
        if info:
            self._sync_worker(info)

    def remove_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        # Nothing to do; heartbeat watcher will eventually mark offline.
        pass

    def _sync_worker(self, info: ServiceInfo) -> None:
        def _decode(value: bytes | None) -> str:
            if value is None:
                return ""
            return value.decode(errors="ignore")

        properties = {k.decode(errors="ignore"): _decode(v) for k, v in (info.properties or {}).items()}
        worker_id = properties.get("id") or info.name.split(".")[0]
        name = properties.get("name") or worker_id
        base_url = properties.get("base_url") or self._build_base_url(info)
        upsert_worker(worker_id=worker_id, name=name, base_url=base_url)

    @staticmethod
    def _build_base_url(info: ServiceInfo) -> str:
        addresses = info.addresses
        if addresses:
            host = socket.inet_ntoa(addresses[0])
        else:
            host = info.server.rstrip(".")
        return f"http://{host}:{info.port}"


class WorkerDiscovery:
    """
    Manage Zeroconf discovery for workers.
    """

    def __init__(self):
        self._zeroconf: Optional[Zeroconf] = None
        self._browser: Optional[ServiceBrowser] = None
        self._listener = WorkerServiceListener()
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._zeroconf is not None:
                return
            self._zeroconf = Zeroconf()
            self._browser = ServiceBrowser(self._zeroconf, SERVICE_TYPE, self._listener)
            log.debug("Worker discovery started")

    def stop(self):
        with self._lock:
            if self._zeroconf:
                try:
                    self._zeroconf.close()
                finally:
                    self._zeroconf = None
                    self._browser = None
                    log.debug("Worker discovery stopped")
