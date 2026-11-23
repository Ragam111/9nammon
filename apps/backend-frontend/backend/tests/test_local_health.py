"""P4 local health payload: reachable, models, available_ram_gb and models_detail, read-only.

Ollama is faked with httpx.MockTransport (through app_client in test_local_routes); the socket guard stays on for
every test. The send path, /api/chat/models and resolve_model are not changed by P4, and the tests below pin that.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.local_provider import DEFAULT_LOCAL_CATALOG
from tests.netguard import GuardedTestCase
from tests.test_local_routes import LOCAL_MODEL, app_client, tags

HEALTH = "/api/chat/local/health"
HEALTH_KEYS = {"reachable", "models", "available_ram_gb", "models_detail"}
DETAIL_KEYS = {"id", "installed", "required_ram_gb"}
ROW_KEYS = {"id", "provider", "label", "configured", "provider_kind", "status", "required_ram_gb", "available_ram_gb"}
CATALOG_IDS = [spec.id for spec in DEFAULT_LOCAL_CATALOG]


def refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


def assert_detail_shape(test: GuardedTestCase, detail: list[dict[str, Any]]) -> None:
    test.assertEqual([entry["id"] for entry in detail], CATALOG_IDS)
    for entry in detail:
        test.assertEqual(set(entry), DETAIL_KEYS)
        test.assertIsInstance(entry["installed"], bool)
        test.assertIsInstance(entry["required_ram_gb"], float)


class LocalHealthPayloadTest(GuardedTestCase):
    def test_health_has_p4_keys_for_signed_in_user(self) -> None:
        with app_client(local=tags(LOCAL_MODEL)) as client:
            res = client.get(HEALTH)
            self.assertEqual(res.status_code, 200)
            body = res.json()
            self.assertEqual(set(body), HEALTH_KEYS)
            self.assertIs(body["reachable"], True)
            self.assertEqual(body["available_ram_gb"], 16.0)
            assert_detail_shape(self, body["models_detail"])
            self.assertEqual(body["models_detail"][0]["installed"], True)

    def test_reachable_and_models_keep_their_values(self) -> None:
        # Same values the pre-P4 route gave: the names are sorted and reachable stays a plain bool.
        with app_client(local=tags("zeta:1b", LOCAL_MODEL)) as client:
            body = client.get(HEALTH).json()
            self.assertIs(body["reachable"], True)
            self.assertEqual(body["models"], sorted(["zeta:1b", LOCAL_MODEL]))

    def test_models_detail_installed_is_false_for_other_tags(self) -> None:
        with app_client(local=tags("llama3:latest")) as client:
            body = client.get(HEALTH).json()
            self.assertEqual(body["models"], ["llama3:latest"])
            assert_detail_shape(self, body["models_detail"])
            self.assertEqual([entry["installed"] for entry in body["models_detail"]], [False])

    def test_unreachable_is_200_with_every_model_not_installed(self) -> None:
        with app_client(local=refuse) as client:
            res = client.get(HEALTH)
            self.assertEqual(res.status_code, 200)
            body = res.json()
            self.assertEqual(set(body), HEALTH_KEYS)
            self.assertIs(body["reachable"], False)
            self.assertEqual(body["models"], [])
            self.assertIn("available_ram_gb", body)
            self.assertTrue(body["available_ram_gb"] is None or isinstance(body["available_ram_gb"], float))
            assert_detail_shape(self, body["models_detail"])
            self.assertTrue(all(entry["installed"] is False for entry in body["models_detail"]))

    def test_without_provider_keeps_keys_and_null_ram(self) -> None:
        with app_client(local=tags(LOCAL_MODEL)) as client:
            client.app.state.ctx.local = None
            res = client.get(HEALTH)
            self.assertEqual(res.status_code, 200)
            body = res.json()
            self.assertEqual(set(body), HEALTH_KEYS)
            self.assertIs(body["reachable"], False)
            self.assertEqual(body["models"], [])
            self.assertIsNone(body["available_ram_gb"])
            assert_detail_shape(self, body["models_detail"])
            self.assertTrue(all(entry["installed"] is False for entry in body["models_detail"]))

    def test_unauthenticated_health_is_rejected_without_data(self) -> None:
        with app_client(local=tags(LOCAL_MODEL)) as client:
            client.cookies.clear()
            res = client.get(HEALTH)
            self.assertEqual(res.status_code, 401)
            for leaked in ("reachable", "models_detail", "available_ram_gb", LOCAL_MODEL):
                self.assertNotIn(leaked, res.text)

    def test_models_route_row_keys_are_unchanged(self) -> None:
        with app_client(local=tags(LOCAL_MODEL)) as client:
            rows = client.get("/api/chat/models").json()["models"]
            self.assertTrue(rows)
            for row in rows:
                self.assertEqual(set(row), ROW_KEYS)

    def test_installed_flag_matches_latest_tag_rule(self) -> None:
        from app.local_provider import installed_flag

        self.assertTrue(installed_flag("llama3", ["llama3:latest"]))
        self.assertFalse(installed_flag("llama3", ["llama3:8b"]))
        self.assertTrue(installed_flag(LOCAL_MODEL, [LOCAL_MODEL]))
        self.assertFalse(installed_flag(LOCAL_MODEL, []))
