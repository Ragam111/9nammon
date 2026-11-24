"""pytest hook: every test runs with real socket connections blocked (see tests/netguard.py).

The suite is normally run with unittest, which does not load this file; GuardedTestCase gives the same protection
there. This file only matters when pytest is installed.
"""

from __future__ import annotations

from collections.abc import Iterator

try:
    import pytest
except ImportError:  # pytest is optional for this project
    pytest = None

from tests.netguard import block_sockets

if pytest is not None:

    @pytest.fixture(autouse=True)
    def _block_real_sockets() -> Iterator[None]:
        with block_sockets():
            yield
