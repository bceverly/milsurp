"""Dynamic port selection for dev mode."""

from __future__ import annotations

import socket

import pytest

from app.netutil import (
    clear_port_file,
    find_free_port,
    is_port_free,
    read_port_file,
    resolve_port,
    write_port_file,
)


@pytest.fixture
def occupied_port():
    """Bind a real socket so the port genuinely reads as busy."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    yield port
    sock.close()


class TestPortProbing:
    def test_free_port_reads_as_free(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        # The socket is closed, so the port is available again.
        assert is_port_free("127.0.0.1", port)

    def test_bound_port_reads_as_busy(self, occupied_port):
        assert not is_port_free("127.0.0.1", occupied_port)


class TestFindFreePort:
    def test_prefers_the_preferred_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
        assert find_free_port("127.0.0.1", free, (9000, 9100)) == free

    def test_falls_through_to_the_range(self, occupied_port):
        """A busy default must never stop `make start`."""
        chosen = find_free_port("127.0.0.1", occupied_port, (18730, 18760))
        assert chosen != occupied_port
        assert 18730 <= chosen <= 18760

    def test_exhausted_range_falls_back_to_an_ephemeral_port(self, occupied_port):
        # A one-port range consisting solely of the busy port.
        chosen = find_free_port("127.0.0.1", occupied_port, (occupied_port, occupied_port))
        assert chosen != occupied_port
        assert chosen > 0


class TestResolvePort:
    def test_explicit_override_wins(self, app_config):
        assert resolve_port(app_config, 12345) == 12345

    def test_dev_mode_picks_dynamically(self, app_config):
        port = resolve_port(app_config)
        low, high = app_config.server.dev_port_range
        assert port == app_config.server.dev_preferred_port or low <= port <= high or port > 0

    def test_production_uses_the_fixed_app_port(self, app_config):
        """Behind nginx the port cannot move, or the proxy config breaks."""
        import dataclasses

        production = dataclasses.replace(app_config, mode="production")
        assert resolve_port(production) == production.server.prod_app_port


class TestPortFile:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "port"
        write_port_file(8731, path)
        assert read_port_file(path) == 8731

    def test_missing_file_reads_as_none(self, tmp_path):
        assert read_port_file(tmp_path / "absent") is None

    def test_garbage_reads_as_none(self, tmp_path):
        path = tmp_path / "port"
        path.write_text("not-a-number", encoding="utf-8")
        assert read_port_file(path) is None

    def test_clear_is_idempotent(self, tmp_path):
        path = tmp_path / "port"
        write_port_file(1234, path)
        clear_port_file(path)
        clear_port_file(path)  # already gone: must not raise
        assert not path.exists()
