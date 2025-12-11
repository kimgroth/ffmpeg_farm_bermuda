"""
Worker management utilities.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from sqlmodel import col, select

from .config import HEARTBEAT_TIMEOUT_SECONDS
from .db import session_scope
from .models import Worker, WorkerStatus


def upsert_worker(*, worker_id: str, name: str, base_url: str) -> Worker:
    now = datetime.utcnow()
    with session_scope() as session:
        worker = session.get(Worker, worker_id)
        if worker is None:
            worker = Worker(
                id=worker_id,
                name=name,
                base_url=base_url,
                last_seen=now,
                status=WorkerStatus.ONLINE,
                accept_leases=True,
            )
        else:
            worker.name = name
            worker.base_url = base_url
            if worker.status == WorkerStatus.OFFLINE:
                worker.status = WorkerStatus.ONLINE
            worker.last_seen = now
        session.add(worker)
        session.commit()
        session.refresh(worker)
        return worker


def update_worker_state(worker_id: str, **fields) -> Worker | None:
    with session_scope() as session:
        worker = session.get(Worker, worker_id)
        if worker is None:
            return None
        for key, value in fields.items():
            setattr(worker, key, value)
        session.add(worker)
        session.commit()
        session.refresh(worker)
        return worker


def list_workers() -> list[Worker]:
    with session_scope() as session:
        return session.exec(select(Worker).order_by(Worker.name)).all()


def reap_stale_workers() -> list[str]:
    """
    Mark workers OFFLINE if their heartbeat expired. Returns affected IDs.
    """
    now = datetime.utcnow()
    expiration = now - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)
    expired: list[str] = []
    with session_scope() as session:
        results = session.exec(
            select(Worker).where(
                Worker.last_seen != None,  # noqa: E711
                Worker.last_seen < expiration,
                Worker.status != WorkerStatus.OFFLINE,
            )
        ).all()
        for worker in results:
            worker.status = WorkerStatus.OFFLINE
            worker.accept_leases = False
            expired.append(worker.id)
            session.add(worker)
        session.commit()
    return expired


def stop_worker(worker_id: str, *, force: bool = False) -> Worker | None:
    status = WorkerStatus.FORCE_STOPPING if force else WorkerStatus.STOPPING
    accept_leases = False
    return update_worker_state(worker_id, status=status, accept_leases=accept_leases)


def resume_worker(worker_id: str) -> Worker | None:
    return update_worker_state(worker_id, status=WorkerStatus.ONLINE, accept_leases=True)


def delete_offline_workers() -> int:
    with session_scope() as session:
        offline_workers = session.exec(select(Worker).where(Worker.status == WorkerStatus.OFFLINE)).all()
        count = len(offline_workers)
        for worker in offline_workers:
            session.delete(worker)
        session.commit()
        return count
