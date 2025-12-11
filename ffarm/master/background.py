"""
Background maintenance tasks for the master node.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlmodel import select

from ..config import HEARTBEAT_TIMEOUT_SECONDS, LEASE_DURATION_SECONDS
from ..db import session_scope
from ..jobs import release_jobs_for_worker
from ..models import Job, JobState, Worker, WorkerStatus


async def lease_reaper_task(stop_event: asyncio.Event):
    while not stop_event.is_set():
        expire_leases()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(5, LEASE_DURATION_SECONDS / 3))
        except asyncio.TimeoutError:
            continue


async def heartbeat_reaper_task(stop_event: asyncio.Event):
    while not stop_event.is_set():
        mark_offline_workers()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(5, HEARTBEAT_TIMEOUT_SECONDS / 2))
        except asyncio.TimeoutError:
            continue


def expire_leases():
    now = datetime.utcnow()
    with session_scope() as session:
        expiring_jobs = session.exec(
            select(Job).where(
                Job.state.in_([JobState.LEASED, JobState.RUNNING]),
                Job.lease_until != None,  # noqa: E711
                Job.lease_until < now,
            )
        ).all()
        for job in expiring_jobs:
            job.state = JobState.PENDING
            job.worker_id = None
            job.lease_until = None
            session.add(job)
        session.commit()


def mark_offline_workers():
    if HEARTBEAT_TIMEOUT_SECONDS <= 0:
        return
    threshold = datetime.utcnow() - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)
    released_workers: list[str] = []
    with session_scope() as session:
        stale_workers = session.exec(
            select(Worker).where(
                Worker.last_seen != None,  # noqa: E711
                Worker.last_seen < threshold,
                Worker.status != WorkerStatus.OFFLINE,
            )
        ).all()
        for worker in stale_workers:
            worker.status = WorkerStatus.OFFLINE
            worker.accept_leases = False
            worker.running_job_id = None
            session.add(worker)
            released_workers.append(worker.id)
        session.commit()
    for worker_id in released_workers:
        release_jobs_for_worker(worker_id)
