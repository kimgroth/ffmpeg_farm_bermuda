"""
Tkinter GUI for the master node.
"""

from __future__ import annotations

import logging
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from sqlmodel import select

from ..config import APP_NAME, GUI_REFRESH_INTERVAL_MS
from ..db import session_scope
from ..discovery import WorkerDiscovery
from ..master_discovery import MasterAdvertiser
from ..jobs import delete_all_jobs, delete_jobs, delete_succeeded_jobs, enqueue_folder, reset_failed_jobs
from ..models import Job, JobState, Worker, WorkerStatus
from ..state import state as master_state
from ..workers import delete_offline_workers, list_workers, resume_worker, stop_worker
from ..worker import WorkerClient
from .server import MasterServer

log = logging.getLogger(__name__)


class MasterGUI:
    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        self.host = host
        self.port = port
        self.server = MasterServer(host=self.host, port=self.port)
        self.discovery = WorkerDiscovery()
        self.advertiser = MasterAdvertiser(host=self.host, port=self.port)
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.run_local_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Idle")
        self.pending_var = tk.StringVar(value="Pending: 0")
        self.failed_var = tk.StringVar(value="Failed: 0")

        self.jobs_tree = None
        self.workers_tree = None
        self.local_worker: WorkerClient | None = None
        self.local_worker_thread: threading.Thread | None = None

        self._build_layout()

    def _build_layout(self):
        control_frame = ttk.Frame(self.root, padding=10)
        control_frame.pack(fill=tk.X)

        choose_button = ttk.Button(control_frame, text="Choose Folder & Enqueue", command=self.choose_folder)
        choose_button.pack(side=tk.LEFT)

        local_check = ttk.Checkbutton(
            control_frame,
            text="Run locally",
            variable=self.run_local_var,
            command=self.toggle_local_worker,
        )
        local_check.pack(side=tk.LEFT, padx=10)

        pause_button = ttk.Button(control_frame, text="Pause", command=self.pause_queue)
        pause_button.pack(side=tk.LEFT, padx=5)

        resume_button = ttk.Button(control_frame, text="Resume", command=self.resume_queue)
        resume_button.pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(control_frame, textvariable=self.status_var)
        self.status_label.pack(side=tk.LEFT, padx=10)
        self.pending_label = ttk.Label(control_frame, textvariable=self.pending_var)
        self.pending_label.pack(side=tk.LEFT, padx=5)
        self.failed_label = ttk.Label(control_frame, textvariable=self.failed_var)
        self.failed_label.pack(side=tk.LEFT, padx=5)

        workers_frame = ttk.Labelframe(self.root, text="Workers", padding=10)
        workers_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.workers_tree = ttk.Treeview(
            workers_frame,
            columns=("name", "status", "job", "accept_leases", "last_seen"),
            show="headings",
            height=6,
        )
        for col, heading in [
            ("name", "Name"),
            ("status", "Status"),
            ("job", "Job"),
            ("accept_leases", "Leasing"),
            ("last_seen", "Last Seen"),
        ]:
            self.workers_tree.heading(col, text=heading)
            self.workers_tree.column(col, stretch=True, width=100)
        self.workers_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        worker_button_frame = ttk.Frame(workers_frame)
        worker_button_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5)

        soft_button = ttk.Button(worker_button_frame, text="Soft Stop", command=self.soft_stop_worker)
        soft_button.pack(fill=tk.X, pady=2)
        hard_button = ttk.Button(worker_button_frame, text="Hard Stop", command=self.hard_stop_worker)
        hard_button.pack(fill=tk.X, pady=2)
        resume_button = ttk.Button(worker_button_frame, text="Resume", command=self.resume_worker)
        resume_button.pack(fill=tk.X, pady=2)
        clear_offline_button = ttk.Button(
            worker_button_frame, text="Clear Offline", command=self.clear_offline_workers
        )
        clear_offline_button.pack(fill=tk.X, pady=2)

        jobs_frame = ttk.Labelframe(self.root, text="Jobs", padding=10)
        jobs_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.jobs_tree = ttk.Treeview(
            jobs_frame,
            columns=("input", "state", "progress", "fps", "worker", "attempts"),
            show="headings",
            height=10,
        )
        for col, heading, width in [
            ("input", "Input", 280),
            ("state", "State", 80),
            ("progress", "Progress", 80),
            ("fps", "FPS", 70),
            ("worker", "Worker", 120),
            ("attempts", "Attempts", 70),
        ]:
            self.jobs_tree.heading(col, text=heading)
            self.jobs_tree.column(col, stretch=True, width=width)
        self.jobs_tree.pack(fill=tk.BOTH, expand=True)

        jobs_button_frame = ttk.Frame(jobs_frame)
        jobs_button_frame.pack(fill=tk.X, pady=(10, 0))

        retry_button = ttk.Button(jobs_button_frame, text="Retry Failed", command=self.retry_failed)
        retry_button.pack(side=tk.LEFT)

        clear_button = ttk.Button(jobs_button_frame, text="Clear Succeeded", command=self.clear_succeeded)
        clear_button.pack(side=tk.LEFT, padx=5)

        clear_all_button = ttk.Button(jobs_button_frame, text="Clear All Jobs", command=self.clear_all_jobs)
        clear_all_button.pack(side=tk.LEFT)

        clear_selected_button = ttk.Button(
            jobs_button_frame, text="Clear Selected", command=self.clear_selected_jobs
        )
        clear_selected_button.pack(side=tk.LEFT, padx=5)

    def start(self):
        self.server.start()
        self.discovery.start()
        self.advertiser.start()
        self.refresh()
        self.root.mainloop()

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        try:
            added, skipped = enqueue_folder(Path(folder))
            self.status_var.set(f"Enqueued {added} jobs (skipped {skipped})")
        except Exception as exc:  # noqa: BLE001
            log.exception("Failed to enqueue jobs")
            messagebox.showerror("Error", f"Unable to enqueue jobs:\n{exc}")

    def refresh(self):
        self._refresh_workers()
        self._refresh_jobs()
        self.root.after(GUI_REFRESH_INTERVAL_MS, self.refresh)

    def pause_queue(self):
        master_state.set_paused(True)
        self.status_var.set("Queue paused")

    def resume_queue(self):
        master_state.set_paused(False)
        self.status_var.set("Queue resumed")

    def _refresh_workers(self):
        selected = set(self.workers_tree.selection())
        focused = self.workers_tree.focus()
        self.workers_tree.delete(*self.workers_tree.get_children())
        for worker in list_workers():
            job_display = worker.running_job_id or "-"
            self.workers_tree.insert(
                "",
                tk.END,
                iid=worker.id,
                values=(
                    worker.name,
                    worker.status,
                    job_display,
                    "Yes" if worker.accept_leases else "No",
                    worker.last_seen.isoformat() if worker.last_seen else "-",
                ),
            )
        for worker_id in selected:
            if self.workers_tree.exists(worker_id):
                self.workers_tree.selection_add(worker_id)
        if focused and self.workers_tree.exists(focused):
            self.workers_tree.focus(focused)

    def _refresh_jobs(self):
        selected = set(self.jobs_tree.selection())
        focused = self.jobs_tree.focus()
        self.jobs_tree.delete(*self.jobs_tree.get_children())
        with session_scope() as session:
            jobs = session.exec(select(Job).order_by(Job.created_at)).all()
        worker_names = {worker.id: worker.name for worker in list_workers()}
        pending = 0
        failed = 0
        for job in jobs:
            if job.state == JobState.PENDING:
                pending += 1
            elif job.state == JobState.FAILED:
                failed += 1
            fps_display = self._format_fps(job.stdout_tail)
            worker_display = "-"
            if job.worker_id:
                worker_display = worker_names.get(job.worker_id, job.worker_id)
            self.jobs_tree.insert(
                "",
                tk.END,
                iid=str(job.id),
                values=(
                    Path(job.input_path).name,
                    job.state,
                    f"{job.progress * 100:.1f}%",
                    fps_display,
                    worker_display,
                    job.attempts,
                ),
            )
        for job_id in selected:
            if self.jobs_tree.exists(job_id):
                self.jobs_tree.selection_add(job_id)
        if focused and self.jobs_tree.exists(focused):
            self.jobs_tree.focus(focused)
        self.pending_var.set(f"Pending: {pending}")
        self.failed_var.set(f"Failed: {failed}")

    @staticmethod
    def _format_fps(stdout_tail: str | None) -> str:
        if not stdout_tail:
            return "-"
        matches = re.findall(r"fps=([0-9]+(?:\.[0-9]+)?)", stdout_tail)
        if not matches:
            return "-"
        try:
            value = float(matches[-1])
        except ValueError:
            return "-"
        return f"{value:.1f}"

    def soft_stop_worker(self):
        worker_id = self._selected_worker_id()
        if not worker_id:
            messagebox.showinfo("Workers", "Select a worker first.")
            return
        stop_worker(worker_id, force=False)

    def hard_stop_worker(self):
        worker_id = self._selected_worker_id()
        if not worker_id:
            messagebox.showinfo("Workers", "Select a worker first.")
            return
        stop_worker(worker_id, force=True)

    def resume_worker(self):
        worker_id = self._selected_worker_id()
        if not worker_id:
            messagebox.showinfo("Workers", "Select a worker first.")
            return
        resume_worker(worker_id)
        self.refresh()

    def retry_failed(self):
        count = reset_failed_jobs()
        self.status_var.set(f"Queued {count} failed jobs for retry")
        self.refresh()

    def clear_succeeded(self):
        count = delete_succeeded_jobs()
        self.status_var.set(f"Cleared {count} succeeded jobs")
        self.refresh()

    def clear_all_jobs(self):
        confirm = messagebox.askyesno("Confirm", "Are you sure??")
        if not confirm:
            return
        count = delete_all_jobs()
        self.status_var.set(f"Deleted {count} jobs")
        self.refresh()

    def clear_selected_jobs(self):
        selection = self.jobs_tree.selection()
        if not selection:
            messagebox.showinfo("Jobs", "Select at least one job.")
            return
        job_ids = []
        for item in selection:
            try:
                job_ids.append(int(item))
            except ValueError:
                continue
        if not job_ids:
            return
        confirm = messagebox.askyesno("Confirm", f"Remove {len(job_ids)} selected job(s)?")
        if not confirm:
            return
        count = delete_jobs(job_ids)
        self.status_var.set(f"Deleted {count} selected jobs")
        self.refresh()

    def clear_offline_workers(self):
        count = delete_offline_workers()
        self.status_var.set(f"Removed {count} offline workers")
        self.refresh()

    def _selected_worker_id(self) -> str | None:
        selection = self.workers_tree.selection()
        if not selection:
            return None
        return selection[0]

    def toggle_local_worker(self):
        if self.run_local_var.get():
            if self.local_worker_thread and self.local_worker_thread.is_alive():
                return
            self.local_worker = WorkerClient(
                f"http://127.0.0.1:{self.port}",
                name="Master Local Worker",
                advertise=False,
            )
            self.local_worker_thread = threading.Thread(target=self.local_worker.run, daemon=True)
            self.local_worker_thread.start()
            self.status_var.set("Local worker running")
        else:
            if self.local_worker:
                self.local_worker.stop()
            if self.local_worker_thread:
                self.local_worker_thread.join(timeout=1.0)
            self.status_var.set("Local worker stopped")

    def on_close(self):
        if self.local_worker:
            self.local_worker.stop()
        if self.local_worker_thread:
            self.local_worker_thread.join(timeout=1.0)
        self.discovery.stop()
        self.advertiser.stop()
        self.server.stop()
        self.root.destroy()
