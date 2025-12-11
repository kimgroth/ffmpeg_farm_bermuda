"""
Module entry point delegating to master or worker CLI.
"""

from __future__ import annotations

import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m ffarm [master|worker] [options...]")
        sys.exit(1)
    command = sys.argv[1]
    argv = [sys.argv[0]] + sys.argv[2:]
    if command == "master":
        from .master.main import main as master_main

        sys.argv = argv
        master_main()
    elif command == "worker":
        from .worker.main import main as worker_main

        sys.argv = argv
        worker_main()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
