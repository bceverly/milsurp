"""Port selection for dev mode.

`make start` must never fail because something else already holds the default
port, so the preferred port is probed and the first free port in the configured
range is used instead. The chosen port is written to a file the Makefile reads
back, which is how `make start` knows which URL to print and `make stop` knows
what to shut down.
"""

from __future__ import annotations

import socket
from pathlib import Path

from .config import ROOT_DIR, Config

PORT_FILE = ROOT_DIR / ".milsurp-dev-port"


def is_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # Without SO_REUSEADDR a port in TIME_WAIT reads as busy, which would
        # make a quick stop/start cycle pick a different port every time.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_free_port(host: str, preferred: int, port_range: tuple[int, int]) -> int:
    """First free port: the preferred one, then the range, then anything.

    A ``preferred`` of 0 skips straight to an OS-assigned ephemeral port.
    """
    if preferred and is_port_free(host, preferred):
        return preferred

    low, high = port_range
    for port in range(low, high + 1):
        if port != preferred and is_port_free(host, port):
            return port

    # Every configured port is taken; let the OS pick an ephemeral one rather
    # than refusing to start.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def resolve_port(config: Config, override: int | None = None) -> int:
    # 0 means "any free port": used by the end-to-end suite, which must not
    # collide with a development server the operator already has running.
    if override == 0:
        return find_free_port(config.host, 0, (1, 0))
    if override:
        return override
    if config.is_dev:
        return find_free_port(
            config.server.dev_host,
            config.server.dev_preferred_port,
            config.server.dev_port_range,
        )
    # Behind nginx the app port is fixed; a moving target would break the
    # reverse-proxy config.
    return config.server.prod_app_port


def write_port_file(port: int, path: Path = PORT_FILE) -> None:
    path.write_text(f"{port}\n", encoding="utf-8")


def read_port_file(path: Path = PORT_FILE) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def clear_port_file(path: Path = PORT_FILE) -> None:
    path.unlink(missing_ok=True)
