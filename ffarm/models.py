"""
Database models and Pydantic schemas shared by the application.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class JobState(str):
    PENDING = "PENDING"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class WorkerStatus(str):
    ONLINE = "ONLINE"
    STOPPING = "STOPPING"
    FORCE_STOPPING = "FORCE_STOPPING"
    STOPPED = "STOPPED"
    OFFLINE = "OFFLINE"


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    input_path: str = Field(index=True)
    output_path: str = Field(index=True)
    profile: str = Field(default="prores_proxy_1280")
    state: str = Field(default=JobState.PENDING, index=True)
    worker_id: Optional[str] = Field(default=None, index=True)
    lease_until: Optional[datetime] = Field(default=None, index=True)
    progress: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    return_code: Optional[int] = None
    stderr_tail: Optional[str] = None
    stdout_tail: Optional[str] = None
    attempts: int = Field(default=0)
    error_message: Optional[str] = None


class Worker(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    base_url: str
    last_seen: Optional[datetime] = Field(default=None, index=True)
    status: str = Field(default=WorkerStatus.ONLINE, index=True)
    running_job_id: Optional[int] = Field(default=None, index=True)
    accept_leases: bool = Field(default=True)


class LeaseResponse(SQLModel):
    job_id: Optional[int] = None
    profile: Optional[str] = None
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    ffmpeg_args: list[str] = Field(default_factory=list)
    accept_leases: bool = True
    action: Optional[str] = None  # e.g. "force_stop"


class HeartbeatRequest(SQLModel):
    worker_id: str
    name: str
    base_url: str
    running_job_id: Optional[int] = None
    status: str = WorkerStatus.ONLINE


class LeaseRequest(SQLModel):
    worker_id: str
    name: str
    base_url: str


class ProgressUpdate(SQLModel):
    worker_id: str
    progress: float = 0.0
    stderr_tail: Optional[str] = None
    stdout_tail: Optional[str] = None


class CompletionReport(SQLModel):
    worker_id: str
    success: bool
    return_code: int
    stderr_tail: Optional[str] = None
    stdout_tail: Optional[str] = None
    error_message: Optional[str] = None
