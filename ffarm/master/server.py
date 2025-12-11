"""
Utilities to run the master FastAPI application.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Optional

import uvicorn
from .api import create_app
from .background import heartbeat_reaper_task, lease_reaper_task


class MasterServer:
    """
    Run the FastAPI server and background tasks in a dedicated asyncio loop.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        self.host = host
        self.port = port
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._server: Optional[uvicorn.Server] = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="ffarm-master-server")
        self._thread.start()

    def _run(self):
        asyncio.run(self._async_main())

    async def _async_main(self):
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        app = create_app()
        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)
        self._server = server

        async def run_server():
            await server.serve()

        tasks = [
            asyncio.create_task(run_server(), name="uvicorn"),
            asyncio.create_task(lease_reaper_task(self._stop_event), name="lease-reaper"),
            asyncio.create_task(heartbeat_reaper_task(self._stop_event), name="heartbeat-reaper"),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    def stop(self):
        if self._loop and not self._loop.is_closed() and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._server:
            self._server.should_exit = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
