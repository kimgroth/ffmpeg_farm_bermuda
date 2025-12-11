"""
Zeroconf utilities for advertising the master server and discovering it from workers.
"""

from __future__ import annotations

import logging
import socket
import threading
import uuid
from typing import Optional

from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

from .config import MASTER_SERVICE_TYPE

log = logging.getLogger(__name__)


def _get_default_ip() -> str:
    """
    Attempt to determine the primary outbound IP by opening a UDP socket.
    Falls back to localhost if no network is available.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


class MasterAdvertiser:
    """
    Registers the master HTTP endpoint on the local network via Zeroconf.
    """

    def __init__(self, host: str, port: int, name: Optional[str] = None):
        self.host = host
        self.port = port
        self.name = name or "FFarm Master"
        self._zeroconf: Optional[Zeroconf] = None
        self._service_info: Optional[ServiceInfo] = None
        self._service_id = f"master-{uuid.uuid4()}"

    def start(self):
        if self._zeroconf is not None:
            return
        ip = self._select_ip()
        base_url = f"http://{ip}:{self.port}"
        self._zeroconf = Zeroconf()
        info = ServiceInfo(
            type_=MASTER_SERVICE_TYPE,
            name=f"{self._service_id}.{MASTER_SERVICE_TYPE}",
            addresses=[socket.inet_aton(ip)],
            port=self.port,
            properties={
                b"id": self._service_id.encode(),
                b"name": self.name.encode(),
                b"base_url": base_url.encode(),
            },
        )
        self._service_info = info
        self._zeroconf.register_service(info)
        log.info("Master advertised via Zeroconf at %s", base_url)

    def stop(self):
        if not self._zeroconf or not self._service_info:
            return
        try:
            self._zeroconf.unregister_service(self._service_info)
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._zeroconf.close()
            self._zeroconf = None
            self._service_info = None

    def _select_ip(self) -> str:
        if self.host not in {"0.0.0.0", "::"}:
            return self.host
        return _get_default_ip()


class _MasterListener(ServiceListener):
    def __init__(self):
        self._event = threading.Event()
        self._base_url: Optional[str] = None

    def wait(self, timeout: float) -> Optional[str]:
        self._event.wait(timeout)
        return self._base_url

    def add_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        info = zeroconf.get_service_info(type_, name)
        if info:
            self._base_url = self._info_to_url(info)
            self._event.set()

    def update_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        if self._base_url:
            return
        info = zeroconf.get_service_info(type_, name)
        if info:
            self._base_url = self._info_to_url(info)
            self._event.set()

    def remove_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
        # Nothing to do for discovery purposes.
        pass

    @staticmethod
    def _info_to_url(info: ServiceInfo) -> str:
        base_url = (info.properties or {}).get(b"base_url")
        if base_url:
            return base_url.decode(errors="ignore")
        if info.addresses:
            host = socket.inet_ntoa(info.addresses[0])
        else:
            host = info.server.rstrip(".")
        port = info.port or 8000
        return f"http://{host}:{port}"


def discover_master(timeout: float = 10.0) -> Optional[str]:
    """
    Listen for a master advertisement and return its base URL.
    """
    zeroconf = Zeroconf()
    listener = _MasterListener()
    ServiceBrowser(zeroconf, MASTER_SERVICE_TYPE, listener)
    try:
        base_url = listener.wait(timeout)
        if base_url:
            log.info("Discovered master at %s via Zeroconf", base_url)
        return base_url
    finally:
        zeroconf.close()
