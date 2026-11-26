"""B6-1: complete() wraps read timeouts/OSError as GatewayError (server then refunds)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import openai_gateway  # noqa: E402


class _Resp:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *a) -> None:
        return None

    def read(self) -> bytes:
        raise self.exc


class CompleteErrorsTest(unittest.TestCase):
    def _run(self, exc: BaseException) -> openai_gateway.GatewayError:
        with self.assertRaises(openai_gateway.GatewayError) as cm:
            openai_gateway.complete({"model": "m", "messages": []},
                                    opener=lambda req, timeout: _Resp(exc))
        return cm.exception

    def test_timeout_is_gateway_error(self) -> None:
        self.assertEqual(self._run(TimeoutError("slow")).status, 504)

    def test_oserror_is_gateway_error(self) -> None:
        self.assertEqual(self._run(ConnectionResetError("rst")).status, 502)


if __name__ == "__main__":
    unittest.main()
