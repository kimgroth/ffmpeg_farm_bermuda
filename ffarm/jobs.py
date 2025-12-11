"""
Job management utilities.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Set

from sqlmodel import select

from .config import LEASE_DURATION_SECONDS
from .db import session_scope
from .models import Job, JobState
from .profiles import PROFILES, OUTPUT_PATTERN

VIDEO_EXTENSIONS = {".mov", ".mp4", ".mxf", ".mkv", ".avi", ".m4v"}


def enqueue_folder(root: Path, profile: str = "prores_proxy_1280") -> tuple[int, int]:
    """
    Scan `root` for videos and enqueue jobs for any that do not yet exist.

    Returns (added, skipped).
    """
    root = Path(root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(root)

    proxies_dir = root / "PROXIES"
    proxies_dir.mkdir(parents=True, exist_ok=True)

    added = 0
    skipped = 0

    with session_scope() as session:
        existing_outputs: Set[str] = {
            row[0] for row in session.exec(select(Job.output_path)).all()
        }
        for input_path in iter_videos(root):
            output_path = derive_output_path(input_path, proxies_dir, existing_outputs)
            existing = session.exec(
                select(Job).where(Job.input_path == str(input_path))
            ).first()
            if existing:
                skipped += 1
                continue
            job = Job(
                input_path=str(input_path),
                output_path=str(output_path),
                profile=profile,
                state=JobState.PENDING,
            )
            session.add(job)
            existing_outputs.add(str(output_path))
            added += 1
        session.commit()
    return added, skipped


def iter_videos(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "PROXIES"]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix.lower() in VIDEO_EXTENSIONS:
                yield path


def derive_output_path(input_path: Path, proxies_dir: Path, existing_outputs: Set[str]) -> Path:
    stem = input_path.stem
    candidate = proxies_dir / OUTPUT_PATTERN.format(stem=stem)
    counter = 1
    while str(candidate) in existing_outputs or candidate.exists():
        candidate = proxies_dir / OUTPUT_PATTERN.format(stem=f"{stem}_{counter}")
        counter += 1
    return candidate


def lease_next_job(worker_id: str, now: datetime | None = None) -> Job | None:
    now = now or datetime.utcnow()
    with session_scope() as session:
        pending_job = session.exec(
            select(Job)
            .where(Job.state == JobState.PENDING)
            .order_by(Job.created_at)
        ).first()

        if pending_job is None:
            # try to steal expired leases
            pending_job = session.exec(
                select(Job).where(
                    Job.state.in_([JobState.LEASED, JobState.RUNNING]),
                    Job.lease_until != None,  # noqa: E711
                    Job.lease_until < now,
                )
            ).first()

        if pending_job is None:
            return None

        pending_job.state = JobState.LEASED
        pending_job.worker_id = worker_id
        pending_job.lease_until = now + timedelta(seconds=LEASE_DURATION_SECONDS)
        pending_job.attempts += 1
        if pending_job.started_at is None:
            pending_job.started_at = now
        session.add(pending_job)
        session.commit()
        session.refresh(pending_job)
        return pending_job


def update_lease(job_id: int, worker_id: str, progress: float | None = None):
    now = datetime.utcnow()
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None or job.worker_id != worker_id:
            return
        job.state = JobState.RUNNING
        job.lease_until = now + timedelta(seconds=LEASE_DURATION_SECONDS)
        if progress is not None:
            job.progress = float(progress)
        session.add(job)
        session.commit()


def complete_job(
    job_id: int,
    worker_id: str,
    *,
    success: bool,
    return_code: int,
    stderr_tail: str | None = None,
    stdout_tail: str | None = None,
    error_message: str | None = None,
):
    now = datetime.utcnow()
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None or job.worker_id != worker_id:
            return
        job.state = JobState.SUCCEEDED if success else JobState.FAILED
        job.finished_at = now
        job.return_code = return_code
        if success:
            job.progress = 1.0
        job.stderr_tail = stderr_tail
        job.stdout_tail = stdout_tail
        job.error_message = error_message
        job.lease_until = None
        session.add(job)
        session.commit()


def reset_failed_jobs() -> int:
    with session_scope() as session:
        jobs = session.exec(select(Job).where(Job.state == JobState.FAILED)).all()
        for job in jobs:
            job.state = JobState.PENDING
            job.progress = 0.0
            job.worker_id = None
            job.lease_until = None
            job.started_at = None
            job.finished_at = None
            job.return_code = None
            job.stderr_tail = None
            job.stdout_tail = None
            job.error_message = None
            session.add(job)
        session.commit()
        return len(jobs)


def delete_succeeded_jobs() -> int:
    with session_scope() as session:
        jobs = session.exec(select(Job).where(Job.state == JobState.SUCCEEDED)).all()
        count = len(jobs)
        for job in jobs:
            session.delete(job)
        session.commit()
        return count


def delete_all_jobs() -> int:
    with session_scope() as session:
        jobs = session.exec(select(Job)).all()
        count = len(jobs)
        for job in jobs:
            session.delete(job)
        session.commit()
        return count


def delete_jobs(job_ids: list[int]) -> int:
    if not job_ids:
        return 0
    with session_scope() as session:
        jobs = session.exec(select(Job).where(Job.id.in_(job_ids))).all()
        for job in jobs:
            session.delete(job)
        session.commit()
        return len(jobs)


def release_jobs_for_worker(worker_id: str) -> int:
    """
    Return any leased or running jobs assigned to the given worker back to the queue.
    """
    with session_scope() as session:
        jobs = session.exec(
            select(Job).where(
                Job.worker_id == worker_id,
                Job.state.in_([JobState.LEASED, JobState.RUNNING]),
            )
        ).all()
        if not jobs:
            return 0
        for job in jobs:
            job.state = JobState.PENDING
            job.worker_id = None
            job.lease_until = None
            job.progress = 0.0
            job.started_at = None
            job.finished_at = None
            job.return_code = None
            job.stderr_tail = None
            job.stdout_tail = None
            job.error_message = None
            session.add(job)
        session.commit()
        return len(jobs)
