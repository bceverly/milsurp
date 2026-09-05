#!/usr/bin/env python3
"""Server entry point for both `make start` (dev) and systemd (production).

In dev the port is chosen dynamically so a busy default never blocks a start;
the chosen port is written to ``.milsurp-dev-port`` and printed as a URL. In
production the port is fixed by the config file, because nginx proxies to it.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow `python backend/run.py` from anywhere in the tree.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn

from app.config import get_config
from app.netutil import resolve_port, write_port_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Milsurp Monitor server.")
    parser.add_argument("--host", default=None, help="Override the bind address.")
    parser.add_argument("--port", type=int, default=None, help="Override the port.")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes.")
    parser.add_argument(
        "--print-url", action="store_true", help="Print the URL and exit (used by make)."
    )
    args = parser.parse_args()

    config = get_config()
    host = args.host or config.host
    port = resolve_port(config, args.port)

    display_host = "localhost" if host in ("0.0.0.0", "127.0.0.1") else host
    url = f"http://{display_host}:{port}"

    if args.print_url:
        print(url)
        return 0

    if config.is_dev:
        write_port_file(port)

    print(f"Milsurp Monitor listening on {url}", flush=True)

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=args.reload,
        # A single worker is required: scan progress and the login throttle live
        # in process memory, and SQLite writes are serialized anyway.
        workers=1,
        log_level=os.environ.get("MILSURP_LOG_LEVEL", "info").lower(),
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
