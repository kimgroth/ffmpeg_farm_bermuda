"""
FastAPI router for master node control plane.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from sqlmodel import select

from ..jobs import complete_job, delete_all_jobs, lease_next_job, update_lease
from ..models import (
    CompletionReport,
    HeartbeatRequest,
    Job,
    JobState,
    LeaseRequest,
    LeaseResponse,
    ProgressUpdate,
    Worker,
    WorkerStatus,
)
from ..profiles import build_profile_command
from ..state import state as master_state
from ..workers import (
    delete_offline_workers,
    list_workers,
    resume_worker,
    stop_worker,
    upsert_worker,
    update_worker_state,
)
from ..db import session_scope


def create_app() -> FastAPI:
    app = FastAPI(title="FFarm Master API")
    router = APIRouter(prefix="/api/v1")

    @router.post("/jobs/lease", response_model=LeaseResponse)
    async def lease_job(request: LeaseRequest):
        worker = upsert_worker(worker_id=request.worker_id, name=request.name, base_url=request.base_url)
        response = LeaseResponse(accept_leases=worker.accept_leases)
        if worker.status == WorkerStatus.FORCE_STOPPING:
            response.action = "force_stop"
        elif worker.status == WorkerStatus.STOPPING:
            response.action = "stop"
        if master_state.is_paused():
            response.accept_leases = False
            return response
        if not worker.accept_leases or response.action == "force_stop":
            return response
        job = lease_next_job(worker_id=worker.id)
        if job is None or worker.accept_leases is False:
            return response
        ffmpeg_args = build_profile_command(job.profile, job.input_path, job.output_path)
        response.job_id = job.id
        response.profile = job.profile
        response.input_path = job.input_path
        response.output_path = job.output_path
        response.ffmpeg_args = ffmpeg_args
        return response

    @router.post("/jobs/{job_id}/progress")
    async def job_progress(job_id: int, update: ProgressUpdate):
        update_lease(job_id=job_id, worker_id=update.worker_id, progress=update.progress)
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job:
                job.stderr_tail = update.stderr_tail
                job.stdout_tail = update.stdout_tail
                session.add(job)
                session.commit()
        return {"status": "ok"}

    @router.post("/jobs/{job_id}/complete")
    async def job_complete(job_id: int, report: CompletionReport):
        complete_job(
            job_id=job_id,
            worker_id=report.worker_id,
            success=report.success,
            return_code=report.return_code,
            stderr_tail=report.stderr_tail,
            stdout_tail=report.stdout_tail,
            error_message=report.error_message,
        )
        update_worker_state(report.worker_id, running_job_id=None, status=WorkerStatus.ONLINE)
        return {"status": "ok"}

    @router.post("/jobs/clear-all")
    async def clear_all_jobs():
        count = delete_all_jobs()
        return {"deleted": count}

    @router.get("/jobs")
    async def list_jobs():
        with session_scope() as session:
            return session.exec(select(Job).order_by(Job.created_at)).all()

    @router.post("/workers/heartbeat")
    async def heartbeat(body: HeartbeatRequest):
        worker = upsert_worker(worker_id=body.worker_id, name=body.name, base_url=body.base_url)
        update_worker_state(
            body.worker_id,
            last_seen=datetime.utcnow(),
            status=body.status,
            running_job_id=body.running_job_id,
        )
        return {
            "accept_leases": worker.accept_leases,
            "status": worker.status,
        }

    @router.get("/workers")
    async def workers() -> list[Worker]:
        return list_workers()

    @router.post("/workers/{worker_id}/stop")
    async def request_stop(worker_id: str):
        worker = stop_worker(worker_id, force=False)
        if worker is None:
            raise HTTPException(status_code=404, detail="Worker not found")
        return worker

    @router.post("/workers/{worker_id}/force_stop")
    async def request_force_stop(worker_id: str):
        worker = stop_worker(worker_id, force=True)
        if worker is None:
            raise HTTPException(status_code=404, detail="Worker not found")
        return worker

    @router.post("/workers/{worker_id}/resume")
    async def request_resume(worker_id: str):
        worker = resume_worker(worker_id)
        if worker is None:
            raise HTTPException(status_code=404, detail="Worker not found")
        return worker

    @router.post("/workers/clear_offline")
    async def clear_offline_workers():
        count = delete_offline_workers()
        return {"deleted": count}

    app.include_router(router)
    return app
