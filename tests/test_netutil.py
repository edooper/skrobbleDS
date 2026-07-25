"""Tests for the shared port-binding helper (C6)."""
import socket

import pytest

import Upnp.NetUtil as NetUtil


def _udp():
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def test_binds_requested_port_when_free():
    sock = _udp()
    try:
        # Port 0 lets the OS choose, so the call always succeeds
        port = NetUtil.bind_in_range(sock, '127.0.0.1', 0, count=1)
        assert port == 0  # the requested number is returned as passed
        assert sock.getsockname()[1] != 0  # OS assigned a real one
    finally:
        sock.close()


def test_steps_past_a_port_already_in_use():
    held = _udp()
    held.bind(('127.0.0.1', 0))
    taken = held.getsockname()[1]
    sock = _udp()
    try:
        port = NetUtil.bind_in_range(sock, '127.0.0.1', taken, count=50)
        assert port > taken
        assert sock.getsockname()[1] == port
    finally:
        sock.close()
        held.close()


def test_raises_once_the_range_is_exhausted():
    """A host that can bind nothing must fail loudly, not spin forever - the
    SSDP stop-socket loop was previously unbounded."""
    held = _udp()
    held.bind(('127.0.0.1', 0))
    taken = held.getsockname()[1]
    sock = _udp()
    try:
        with pytest.raises(RuntimeError, match='stop socket'):
            NetUtil.bind_in_range(sock, '127.0.0.1', taken, count=1,
                                  what='stop socket')
    finally:
        sock.close()
        held.close()
