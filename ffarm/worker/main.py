"""
CLI entry point for worker process.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .client import WorkerClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FFarm worker node")
    parser.add_argument("--master", help="Master base URL (defaults to Zeroconf discovery)")
    parser.add_argument("--id", dest="worker_id", help="Worker ID (defaults to random UUID)")
    parser.add_argument("--name", help="Friendly worker name")
    parser.add_argument("--no-zeroconf", dest="advertise", action="store_false", help="Disable Zeroconf advertisement")
    parser.set_defaults(advertise=True)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    try:
        worker = WorkerClient(
            args.master,
            worker_id=args.worker_id,
            name=args.name,
            advertise=args.advertise,
        )
    except RuntimeError as exc:
        logging.error("%s", exc)
        sys.exit(1)
    try:
        worker.run()
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    main()
