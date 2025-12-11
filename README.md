# LAN FFmpeg Farm

Distributed FFmpeg transcoding across machines on the same network. The master node exposes an HTTP API and a Tkinter GUI to manage queued media jobs, while workers pull jobs, run FFmpeg with the ProRes Proxy profile, and report progress.

## Highlights

- Auto-discovery of workers via mDNS/ZeroConf (`_ffarm._tcp.local.`).
- Master GUI for scanning folders, monitoring workers, pausing the queue, retrying failures, and clearing completed jobs.
- SQLite backing store via SQLModel.
- Stateless workers that lease jobs with automatic re-assignment if a worker disappears.
- Local worker toggle so the master can contribute processing power.

## Quick Start

```bash
python -m ffarm master             # start the master GUI (runs on port 8000)
python -m ffarm worker             # workers auto-discover the master via mDNS
```

Set `FFARM_MASTER_URL=http://HOST:PORT` or pass `--master` if discovery is unavailable on your network (e.g., different subnets). Both commands require the Python environment described below. FFmpeg must be reachable on the system `PATH`.

## Installation Scripts

The `scripts/` directory provides zero-touch setup for macOS and Ubuntu:

| Script | Purpose |
| ------ | ------- |
| `install_macos.sh` | Installs Command Line Tools, Homebrew, FFmpeg, Python 3, and Python deps. |
| `run_master_macos.command` | Double-click launcher that runs the installer then starts the master GUI. |
| `run_slave_macos.command` | Double-click launcher to start a worker on macOS. |
| `uninstall_macos.sh` | Removes the project virtual environment (leaves Homebrew packages intact). |
| `install_ubuntu.sh` | Installs apt prerequisites, FFmpeg, Python 3, Tk, and Python deps. |
| `run_master_ubuntu.sh` | Launcher for the Ubuntu master node. |
| `run_slave_ubuntu.sh` | Launcher for the Ubuntu worker node. |
| `ffarm-master.desktop` | Optional GNOME desktop entry for the master launcher. |
| `ffarm-slave.desktop` | Optional GNOME desktop entry for the worker launcher. |

Run the installer once per machine; all launchers call it automatically. Ensure the scripts are executable:

```bash
chmod +x scripts/*.sh scripts/*.command
```

## Workflow

1. Launch the master GUI (`run_master_*` or `python -m ffarm master`).
2. Choose a shared root folder and enqueue jobs. Output proxies are written into `<root>/PROXIES` (flat list) as `<FileName>_Proxy.mov`.
3. Start workers on machines that have access to the same shared storage.
4. Monitor progress in the GUI. Use Soft Stop / Hard Stop buttons to drain or terminate workers as needed.
5. If a worker goes offline mid-run, its lease expires and another worker will pick up the job.

## Development Notes

- The API is served from FastAPI (`http://<host>:8000/api/v1/...`).
- SQLite data file lives in `~/.ffarm/ffarm.sqlite3`.
- FFmpeg command profile is defined in `ffarm/profiles.py` and enforces a 1280px long edge with audio copy.
- Worker mDNS advertisement (`zeroconf`) lets the master surface workers as they join; heartbeat failures mark them OFFLINE.
