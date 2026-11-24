"""Blocks real socket connections while a test runs.

asyncio builds its self-pipe with socket.socketpair(), which connects a socket to itself on loopback. That call is
let through; every other connect or connect_ex raises RuntimeError.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import unittest
from collections.abc import Iterator
from typing import Any

_state = threading.local()
_BLOCKED = "real socket connection blocked in tests"


@contextlib.contextmanager
def block_sockets() -> Iterator[None]:
    """Refuse outgoing socket connections for the duration of the block. Nested use is safe."""
    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_socketpair = socket.socketpair

    def allowed() -> bool:
        return getattr(_state, "pair_depth", 0) > 0

    def pair(*args: Any, **kwargs: Any) -> Any:
        _state.pair_depth = getattr(_state, "pair_depth", 0) + 1
        try:
            return orig_socketpair(*args, **kwargs)
        finally:
            _state.pair_depth -= 1

    def connect(self: socket.socket, address: Any) -> None:
        if not allowed():
            raise RuntimeError(_BLOCKED)
        return orig_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        if not allowed():
            raise RuntimeError(_BLOCKED)
        return orig_connect_ex(self, address)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.socketpair = pair  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = orig_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = orig_connect_ex  # type: ignore[method-assign]
        socket.socketpair = orig_socketpair  # type: ignore[assignment]


class GuardedTestCase(unittest.TestCase):
    """unittest base class: every test runs with real socket connections blocked."""

    def setUp(self) -> None:
        super().setUp()
        guard = block_sockets()
        guard.__enter__()
        self.addCleanup(guard.__exit__, None, None, None)
