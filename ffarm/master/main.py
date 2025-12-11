"""
CLI entry point to launch the master GUI.
"""

from __future__ import annotations

import argparse
import logging

from .gui import MasterGUI


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FFarm master node with GUI")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host")
    parser.add_argument("--port", type=int, default=8000, help="HTTP bind port")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    gui = MasterGUI(host=args.host, port=args.port)
    gui.start()


if __name__ == "__main__":
    main()
