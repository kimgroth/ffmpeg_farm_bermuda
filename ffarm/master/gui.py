"""
Tkinter GUI for the master node.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font
from pathlib import Path

from sqlmodel import select

from ..config import APP_NAME, APP_VERSION, GUI_REFRESH_INTERVAL_MS
from ..db import session_scope
from ..discovery import WorkerDiscovery
from ..master_discovery import MasterAdvertiser
from ..jobs import delete_all_jobs, delete_jobs, delete_succeeded_jobs, enqueue_folder, reset_failed_jobs
from ..profiles import PROFILE_CHOICES
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
        self.style = ttk.Style(self.root)
        self.big_font = self._make_big_font()
        self.huge_font = self._make_huge_font()
        self.mode_title_font = self._make_mode_title_font()

        self.mode_var = tk.StringVar(value="master")
        self._refresh_after_id = None
        self._master_services_running = False
        self._themes = {
            "master": {
                "bg": "#0b0b0b",
                "panel": "#0f0f0f",
                "accent": "#1f1f1f",
                "text": "#f5f5f5",
                "muted": "#bdbdbd",
            },
            "worker": {
                "bg": "#0b0b0b",
                "panel": "#0f0f0f",
                "accent": "#1f1f1f",
                "text": "#f5f5f5",
                "muted": "#bdbdbd",
            },
        }

        self.run_local_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Idle")
        self.pending_var = tk.StringVar(value="Pending: 0")
        self.failed_var = tk.StringVar(value="Failed: 0")
        self.profile_label_to_key = {label: key for key, label in PROFILE_CHOICES}
        self.profile_labels = [label for _, label in PROFILE_CHOICES]
        self.profile_var = tk.StringVar(value=self.profile_labels[0])
        self.queue_progress_var = tk.DoubleVar(value=0.0)
        self.queue_progress_text = tk.StringVar(value="Completed 0 / 0")
        self.total_fps_var = tk.StringVar(value="0.0 fps")

        self.jobs_tree = None
        self.workers_tree = None
        self.local_worker: WorkerClient | None = None
        self.local_worker_thread: threading.Thread | None = None
        self.worker_client: WorkerClient | None = None
        self.worker_thread: threading.Thread | None = None
        self.worker_status_var = tk.StringVar(value="Stopped")
        self.worker_activity_var = tk.StringVar(value="Idle")

        self.mode_bar = None
        self.mode_title = None
        self.mode_toggle_frame = None
        self.mode_master_btn = None
        self.mode_worker_btn = None
        self.update_status_var = tk.StringVar(value="")
        self.update_status_label = None
        self.master_frame = None
        self.worker_frame = None
        self.progress_style = "Mode.Horizontal.TProgressbar"

        self._build_layout()

    def _build_layout(self):
        self._build_mode_bar()
        self.master_frame = tk.Frame(self.root, bd=0, highlightthickness=0)
        self.worker_frame = tk.Frame(self.root, bd=0, highlightthickness=0)
        self._build_master_layout(self.master_frame)
        self._build_worker_layout(self.worker_frame)
        self._apply_mode_theme(self.mode_var.get())
        self._show_mode_frame(self.mode_var.get())

    def _build_mode_bar(self):
        self.mode_bar = tk.Frame(self.root, bd=0, highlightthickness=0)
        self.mode_bar.pack(fill=tk.X)

        self.mode_title = tk.Label(
            self.mode_bar,
            text="FFarm",
            font=self.mode_title_font,
            anchor="w",
        )
        self.mode_title.pack(side=tk.LEFT, padx=12, pady=10)

        self.update_status_label = tk.Label(
            self.mode_bar,
            textvariable=self.update_status_var,
            anchor="w",
        )
        self.update_status_label.pack(side=tk.LEFT, padx=12, pady=10)

        self.mode_toggle_frame = tk.Frame(self.mode_bar, bd=0, highlightthickness=0)
        self.mode_toggle_frame.pack(side=tk.RIGHT, padx=10, pady=6)

        self.mode_master_btn = ttk.Button(
            self.mode_toggle_frame,
            text="Master Mode",
            command=lambda: self._set_mode("master"),
            style="Mode.TButton",
        )
        self.mode_master_btn.pack(side=tk.LEFT, padx=4)

        self.mode_worker_btn = ttk.Button(
            self.mode_toggle_frame,
            text="Worker Mode",
            command=lambda: self._set_mode("worker"),
            style="Mode.TButton",
        )
        self.mode_worker_btn.pack(side=tk.LEFT, padx=4)

    def _build_master_layout(self, parent: tk.Misc):
        control_frame = ttk.Frame(parent, padding=10)
        control_frame.pack(fill=tk.X)

        choose_button = ttk.Button(control_frame, text="Choose Folder & Enqueue", command=self.choose_folder)
        choose_button.pack(side=tk.LEFT)
        choose_multi_button = ttk.Button(
            control_frame, text="Choose Folders (Multi)", command=self.choose_folders
        )
        choose_multi_button.pack(side=tk.LEFT, padx=(6, 0))

        profile_label = ttk.Label(control_frame, text="Output Profile")
        profile_label.pack(side=tk.LEFT, padx=(10, 4))
        profile_select = ttk.Combobox(
            control_frame,
            textvariable=self.profile_var,
            values=self.profile_labels,
            state="readonly",
            width=28,
        )
        profile_select.pack(side=tk.LEFT)
        profile_select.current(0)

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

        progress_frame = ttk.Frame(parent, padding=(10, 5))
        progress_frame.pack(fill=tk.X)

        progress_top = ttk.Frame(progress_frame)
        progress_top.pack(fill=tk.X)
        progress_label = ttk.Label(progress_top, textvariable=self.queue_progress_text, font=self.big_font)
        progress_label.pack(side=tk.LEFT, anchor=tk.W)
        fps_label = ttk.Label(progress_top, textvariable=self.total_fps_var, font=self.huge_font)
        fps_label.pack(side=tk.RIGHT, anchor=tk.E)

        self.style.configure(self.progress_style, thickness=28)
        progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.queue_progress_var,
            maximum=1.0,
            mode="determinate",
            length=800,
            style=self.progress_style,
        )
        progress_bar.pack(fill=tk.X, padx=(0, 0), pady=(6, 4))

        workers_frame = ttk.Labelframe(parent, text="Workers", padding=10)
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

        jobs_frame = ttk.Labelframe(parent, text="Jobs", padding=10)
        jobs_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.jobs_tree = ttk.Treeview(
            jobs_frame,
            columns=("input", "profile", "state", "progress", "fps", "worker", "attempts"),
            show="headings",
            height=10,
        )
        for col, heading, width in [
            ("input", "Input", 260),
            ("profile", "Output Profile", 140),
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

    def _build_worker_layout(self, parent: tk.Misc):
        header = ttk.Frame(parent, padding=12)
        header.pack(fill=tk.X)

        title = ttk.Label(header, text="Worker Control", font=self.big_font)
        title.pack(side=tk.LEFT)

        status_label = ttk.Label(header, textvariable=self.worker_status_var, font=self.big_font)
        status_label.pack(side=tk.RIGHT)

        buttons = ttk.Frame(parent, padding=(16, 6))
        buttons.pack(fill=tk.X)
        start_button = ttk.Button(buttons, text="Start Worker", command=self.start_worker)
        start_button.pack(side=tk.LEFT)
        stop_button = ttk.Button(buttons, text="Stop Worker", command=self.stop_worker)
        stop_button.pack(side=tk.LEFT, padx=6)

        status_panel = ttk.Frame(parent, padding=(16, 8))
        status_panel.pack(fill=tk.X)
        activity_label = ttk.Label(status_panel, text="Status", font=self.big_font)
        activity_label.pack(side=tk.LEFT)
        activity_value = ttk.Label(status_panel, textvariable=self.worker_activity_var, font=self.big_font)
        activity_value.pack(side=tk.LEFT, padx=(12, 0))

    def start(self):
        self._auto_update_on_launch()
        self._set_mode(self.mode_var.get(), initial=True)
        self.refresh()
        self.root.mainloop()

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        self._enqueue_paths([Path(folder)])

    def choose_folders(self):
        paths = self._choose_folders_native()
        if not paths:
            messagebox.showinfo(
                "Enqueue",
                "Multi-folder selection requires macOS AppleScript permissions.\n"
                "No folders were enqueued.",
            )
            return
        unique_paths: list[Path] = []
        seen = set()
        for p in paths:
            if p not in seen:
                seen.add(p)
                unique_paths.append(p)
        if not unique_paths:
            messagebox.showinfo("Enqueue", "No folders selected.")
            return
        self._enqueue_paths(unique_paths)

    def _handle_drop(self, event):
        data = event.data
        if not data:
            return
        try:
            parts = self.root.tk.splitlist(data)
        except Exception:  # noqa: BLE001
            parts = data.split()
        paths = []
        for part in parts:
            p = Path(part)
            if p.is_dir():
                paths.append(p)
            elif p.is_file():
                paths.append(p.parent)
        if not paths:
            return
        self._enqueue_paths(paths)

    def _enqueue_paths(self, paths: list[Path]):
        profile_key = self.profile_label_to_key.get(self.profile_var.get(), PROFILE_CHOICES[0][0])
        total_added = 0
        total_skipped = 0
        total_folders = 0
        try:
            for path in paths:
                total_folders += 1
                added, skipped = enqueue_folder(path, profile=profile_key)
                total_added += added
                total_skipped += skipped
            self.status_var.set(
                f"Processed {total_folders} folder(s): enqueued {total_added} jobs (skipped {total_skipped})"
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Failed to enqueue jobs")
            messagebox.showerror("Error", f"Unable to enqueue jobs:\n{exc}")

    def refresh(self):
        if self._master_services_running:
            self._refresh_workers()
            self._refresh_jobs()
        self._refresh_worker_status()
        self._refresh_after_id = self.root.after(GUI_REFRESH_INTERVAL_MS, self.refresh)

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
        completed = 0
        total_fps = 0.0
        for job in jobs:
            if job.state == JobState.PENDING:
                pending += 1
            elif job.state == JobState.FAILED:
                failed += 1
            elif job.state == JobState.SUCCEEDED:
                completed += 1
            fps_display = self._format_fps(job.stdout_tail)
            fps_value = self._extract_fps(job.stdout_tail)
            if job.state == JobState.RUNNING and fps_value is not None:
                total_fps += fps_value
            worker_display = "-"
            if job.worker_id:
                worker_display = worker_names.get(job.worker_id, job.worker_id)
            self.jobs_tree.insert(
                "",
                tk.END,
                iid=str(job.id),
                values=(
                    Path(job.input_path).name,
                    job.profile,
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
        total_jobs = len(jobs)
        ratio = (completed / total_jobs) if total_jobs else 0.0
        self.queue_progress_var.set(ratio)
        self.queue_progress_text.set(f"Completed {completed} / {total_jobs}")
        self.total_fps_var.set(f"{total_fps:.1f} fps")

    @staticmethod
    def _format_fps(stdout_tail: str | None) -> str:
        value = MasterGUI._extract_fps(stdout_tail)
        if value is None:
            return "-"
        return f"{value:.1f}"

    @staticmethod
    def _extract_fps(stdout_tail: str | None) -> float | None:
        if not stdout_tail:
            return None
        matches = re.findall(r"fps=([0-9]+(?:\.[0-9]+)?)", stdout_tail)
        if not matches:
            return None
        try:
            return float(matches[-1])
        except ValueError:
            return None

    @staticmethod
    def _make_big_font():
        base = font.nametofont("TkDefaultFont").copy()
        base.configure(size=12, weight="bold")
        return base

    @staticmethod
    def _make_huge_font():
        base = font.nametofont("TkDefaultFont").copy()
        base.configure(size=20, weight="bold")
        return base

    def _auto_update_on_launch(self):
        self.update_status_var.set("Checking for updates...")
        git_bin = shutil.which("git")
        if not git_bin:
            self.update_status_var.set("Update skipped (git not found)")
            return
        repo_root = Path(__file__).resolve().parents[3]
        if not (repo_root / ".git").exists():
            self.update_status_var.set("Update skipped (not a git checkout)")
            return
        try:
            status = subprocess.run(
                [git_bin, "-C", str(repo_root), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception:  # noqa: BLE001
            self.update_status_var.set("Update failed (status error)")
            return
        if status.stdout.strip():
            self._clean_update_artifacts(repo_root, git_bin)
            try:
                status = subprocess.run(
                    [git_bin, "-C", str(repo_root), "status", "--porcelain"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except Exception:  # noqa: BLE001
                self.update_status_var.set("Update failed (status error)")
                return
            if status.stdout.strip():
                log.info("Auto-update skipped: working tree is dirty.")
                self.update_status_var.set("Update skipped (local changes)")
                return
        try:
            head_before = subprocess.run(
                [git_bin, "-C", str(repo_root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except Exception:  # noqa: BLE001
            self.update_status_var.set("Update failed (git error)")
            return
        try:
            subprocess.run(
                [git_bin, "-C", str(repo_root), "pull", "--ff-only"],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception:  # noqa: BLE001
            self.update_status_var.set("Update skipped (non-fast-forward)")
            return
        try:
            head_after = subprocess.run(
                [git_bin, "-C", str(repo_root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except Exception:  # noqa: BLE001
            self.update_status_var.set("Update failed (git error)")
            return
        if head_before == head_after:
            self.update_status_var.set("Up to date")
            return
        log.info("Auto-update applied. Restarting.")
        self.update_status_var.set("Update applied. Restarting...")
        args = [
            sys.executable,
            "-m",
            "ffarm",
            "master",
            "--host",
            self.host,
            "--port",
            str(self.port),
        ]
        try:
            os.execv(sys.executable, args)
        except Exception:  # noqa: BLE001
            log.exception("Auto-restart failed after update.")

    @staticmethod
    def _clean_update_artifacts(repo_root: Path, git_bin: str):
        cleanup_paths = [
            "ffarm/__pycache__",
            "ffarm/master/__pycache__",
            "ffarm/worker/__pycache__",
            ".DS_Store",
        ]
        try:
            subprocess.run(
                [git_bin, "-C", str(repo_root), "checkout", "--", *cleanup_paths],
                check=False,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [git_bin, "-C", str(repo_root), "clean", "-fd", "--", *cleanup_paths],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:  # noqa: BLE001
            return

    @staticmethod
    def _make_mode_title_font():
        base = font.nametofont("TkDefaultFont").copy()
        base.configure(size=18, weight="bold")
        return base

    def _apply_mode_theme(self, mode: str):
        theme = self._themes.get(mode, self._themes["master"])
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.root.configure(bg=theme["bg"])
        if self.mode_bar:
            self.mode_bar.configure(bg=theme["bg"])
        if self.mode_toggle_frame:
            self.mode_toggle_frame.configure(bg=theme["bg"])
        if self.mode_title:
            self.mode_title.configure(
                text=f"FFarm v{APP_VERSION} — {mode.capitalize()} Mode",
                bg=theme["bg"],
                fg=theme["text"],
            )
        if self.update_status_label:
            self.update_status_label.configure(
                bg=theme["bg"],
                fg=theme["muted"],
            )
        if self.master_frame:
            self.master_frame.configure(bg=theme["panel"])
        if self.worker_frame:
            self.worker_frame.configure(bg=theme["panel"])

        active_bg = theme["accent"]
        inactive_bg = theme["panel"]
        active_fg = theme["text"]
        inactive_fg = theme["muted"]

        self.style.configure(
            "Mode.TButton",
            background=inactive_bg,
            foreground=inactive_fg,
            borderwidth=0,
            focusthickness=0,
            padding=(14, 8),
        )
        self.style.configure(
            "ModeActive.TButton",
            background=active_bg,
            foreground=active_fg,
            borderwidth=0,
            focusthickness=0,
            padding=(14, 8),
        )
        self.style.map(
            "Mode.TButton",
            background=[("active", active_bg)],
            foreground=[("active", active_fg)],
        )
        if self.mode_master_btn and self.mode_worker_btn:
            self.mode_master_btn.configure(
                style="ModeActive.TButton" if mode == "master" else "Mode.TButton"
            )
            self.mode_worker_btn.configure(
                style="ModeActive.TButton" if mode == "worker" else "Mode.TButton"
            )

        self.style.configure(
            self.progress_style,
            troughcolor=theme["panel"],
            background=theme["accent"],
        )

        self.style.configure(
            "TFrame",
            background=theme["panel"],
        )
        self.style.configure(
            "TLabelframe",
            background=theme["panel"],
            foreground=theme["text"],
        )
        self.style.configure(
            "TLabelframe.Label",
            background=theme["panel"],
            foreground=theme["text"],
        )
        self.style.configure(
            "TLabel",
            background=theme["panel"],
            foreground=theme["text"],
        )
        self.style.configure(
            "TButton",
            background=theme["accent"],
            foreground=theme["text"],
            borderwidth=0,
            focusthickness=0,
            padding=(10, 6),
        )
        self.style.map(
            "TButton",
            background=[("active", theme["accent"]), ("pressed", theme["accent"])],
            foreground=[("active", theme["text"]), ("pressed", theme["text"])],
        )
        self.style.configure(
            "TCheckbutton",
            background=theme["panel"],
            foreground=theme["text"],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=theme["bg"],
            background=theme["panel"],
            foreground=theme["text"],
            arrowcolor=theme["text"],
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", theme["bg"])],
            foreground=[("readonly", theme["text"])],
        )
        self.style.configure(
            "Treeview",
            background=theme["bg"],
            fieldbackground=theme["bg"],
            foreground=theme["text"],
            borderwidth=0,
        )
        self.style.map(
            "Treeview",
            background=[("selected", theme["accent"])],
            foreground=[("selected", theme["text"])],
        )
        self.style.configure(
            "Treeview.Heading",
            background=theme["panel"],
            foreground=theme["text"],
            relief="flat",
        )

    def _show_mode_frame(self, mode: str):
        if self.master_frame:
            self.master_frame.pack_forget()
        if self.worker_frame:
            self.worker_frame.pack_forget()
        if mode == "worker":
            self.worker_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self.master_frame.pack(fill=tk.BOTH, expand=True)

    def _set_mode(self, mode: str, initial: bool = False):
        current = self.mode_var.get()
        if not initial and mode == current:
            return
        self.mode_var.set(mode)
        self._apply_mode_theme(mode)
        self._show_mode_frame(mode)
        if mode == "master":
            self._stop_worker()
            self._start_master_services()
        else:
            self._stop_local_worker()
            self._stop_master_services()
            self._refresh_worker_status()

    def _start_master_services(self):
        if self._master_services_running:
            return
        self.server.start()
        self.discovery.start()
        self.advertiser.start()
        self._master_services_running = True
        self.worker_activity_var.set("Idle")

    def _stop_master_services(self):
        if not self._master_services_running:
            return
        self.discovery.stop()
        self.advertiser.stop()
        self.server.stop()
        self._master_services_running = False

    def start_worker(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        master_url = None
        name = None
        advertise = True
        try:
            self.worker_client = WorkerClient(
                master_url,
                name=name,
                advertise=advertise,
            )
        except RuntimeError as exc:
            messagebox.showerror("Worker", str(exc))
            return
        self.worker_status_var.set("Starting...")
        self.worker_thread = threading.Thread(target=self._run_worker, daemon=True)
        self.worker_thread.start()
        self.worker_status_var.set("Running")

    def _run_worker(self):
        try:
            if self.worker_client:
                self.worker_client.run()
        except Exception:  # noqa: BLE001
            log.exception("Worker exited unexpectedly")
            self.root.after(0, lambda: self.worker_status_var.set("Error (see logs)"))
            return
        self.root.after(0, lambda: self.worker_status_var.set("Stopped"))

    def stop_worker(self):
        self._stop_worker()

    def _stop_worker(self):
        if self.worker_client:
            self.worker_client.stop()
        if self.worker_thread:
            self.worker_thread.join(timeout=2.0)
        self.worker_thread = None
        self.worker_client = None
        self.worker_status_var.set("Stopped")
        self.worker_activity_var.set("Idle")

    def _stop_local_worker(self):
        if self.local_worker:
            self.local_worker.stop()
        if self.local_worker_thread:
            self.local_worker_thread.join(timeout=1.0)
        self.local_worker = None
        self.local_worker_thread = None
        self.run_local_var.set(False)

    def _refresh_worker_status(self):
        if self.mode_var.get() != "worker":
            return
        if not self.worker_thread or not self.worker_thread.is_alive():
            self.worker_status_var.set("Stopped")
            self.worker_activity_var.set("Idle")
            return
        if not self.worker_client:
            self.worker_status_var.set("Running")
            self.worker_activity_var.set("Ready")
            return
        current_job = getattr(self.worker_client, "_current_job", None)
        if current_job is None:
            self.worker_status_var.set("Ready")
            self.worker_activity_var.set("Ready")
        else:
            name = Path(current_job.input_path).name
            self.worker_status_var.set("Converting")
            self.worker_activity_var.set(f"Converting {name}")

    def _choose_folders_native(self) -> list[Path] | None:
        """
        macOS-only multi-folder picker via AppleScript. Returns None on failure.
        """
        if sys.platform != "darwin":
            return None
        script = r'''
            set chosenFolders to choose folder with multiple selections allowed
            set output to ""
            repeat with f in chosenFolders
                set output to output & POSIX path of f & linefeed
            end repeat
            return output
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception:
            return None
        paths: list[Path] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            p = Path(line)
            if p.is_dir():
                paths.append(p)
        return paths

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
            self._stop_local_worker()
            self.status_var.set("Local worker stopped")

    def on_close(self):
        if self._refresh_after_id:
            self.root.after_cancel(self._refresh_after_id)
        self._stop_worker()
        self._stop_local_worker()
        self._stop_master_services()
        self.root.destroy()
