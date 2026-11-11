"""Role registry and the port-8421 UI contract.

No listening sockets. Frontend paths come from the files the dashboard actually ships.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lca_core.constants import (  # noqa: E402
    AUTH_REDIRECT_URIS,
    CHUNK_BYTES,
    DASHBOARD_ORIGINS,
    DASHBOARD_PORT,
    GOOGLE_CLIENT_ID,
    WORKER_PORT,
)
from lca_core.logs import AuditLog  # noqa: E402
from lca_core.roles import ROLES, as_config  # noqa: E402
from lca_core.routes import GatewayContext, dispatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONFIG_JS = (ROOT / "local_dashboard" / "web" / "js" / "config.js").read_text(encoding="utf-8")
OAUTH_JS = (ROOT / "local_dashboard" / "web" / "js" / "oauth.js").read_text(encoding="utf-8")
NODES_JS = (ROOT / "local_dashboard" / "web" / "js" / "nodes.js").read_text(encoding="utf-8")
NODE_PANEL_JS = (ROOT / "local_dashboard" / "web" / "js" / "node-panel.js").read_text(encoding="utf-8")
LOG_PANEL_JS = (ROOT / "local_dashboard" / "web" / "js" / "log-panel.js").read_text(encoding="utf-8")
CONTRACT = (ROOT / "docs" / "FRONTEND_BACKEND_CONTRACT.md").read_text(encoding="utf-8")
CORE_DOC = (ROOT / "docs" / "LCA_CORE.md").read_text(encoding="utf-8")

EXPECTED_TITLES = (
    "9arm Manager",
    "New Bot",
    "UOL Bot",
    "Q Botdata",
    "AMD Bot",
    "ULO Bot",
    "Moon Bot",
    "Bot trading",
)


def _up(host, port, timeout):
    return {"status": "up", "latency_ms": 3}


class RoleRegistryTest(unittest.TestCase):
    def test_eight_roles_are_unique_and_local(self):
        config = as_config()
        self.assertEqual(len(ROLES), 8)
        self.assertEqual(len(config), 8)
        titles = [role.title for role in ROLES.values()]
        keys = list(ROLES)
        self.assertEqual(sorted(titles), sorted(EXPECTED_TITLES))
        self.assertEqual(len(set(titles)), 8)
        self.assertEqual(len(set(keys)), 8)
        blob = json.dumps(config)
        self.assertNotIn("http://", blob)
        self.assertNotIn("https://", blob)
        self.assertNotIn("8420", blob)
        self.assertNotIn("8421", blob)
        for item in config.values():
            self.assertFalse(item["network"])
            self.assertTrue(item["modules"])
            self.assertTrue(item["handlers"])
            for name in item["modules"] + item["handlers"]:
                self.assertTrue(name.startswith("lca_core."))

    def test_handlers_import_without_opening_a_port(self):
        modules = sorted({role.modules[0].split(":")[0] for role in ROLES.values()} |
                         {name.split(":")[0] for role in ROLES.values() for name in role.modules} |
                         {spec.split(":")[0] for role in ROLES.values() for spec in role.handlers})
        for role in ROLES.values():
            for spec in role.handlers:
                module_name, attr = spec.split(":")
                module = importlib.import_module(module_name)
                handler = getattr(module, attr)
                self.assertTrue(callable(handler))
        script = (
            "import socket, urllib.request\n"
            "def blocked(*args, **kwargs):\n"
            "    raise RuntimeError('network blocked')\n"
            "socket.socket = blocked\n"
            "socket.create_connection = blocked\n"
            "urllib.request.urlopen = blocked\n"
            "import importlib\n"
            f"mods = {modules!r}\n"
            "for name in mods:\n"
            "    importlib.import_module(name)\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


class DashboardContractTest(unittest.TestCase):
    def test_js_and_contract_share_paths_with_lca_core(self):
        self.assertIn(f'"{GOOGLE_CLIENT_ID}"', CONFIG_JS)
        self.assertIn(GOOGLE_CLIENT_ID, CONTRACT)
        for origin in DASHBOARD_ORIGINS:
            self.assertIn(f'"{origin}"', CONFIG_JS)
            self.assertIn(origin, CONTRACT)
            self.assertIn(origin, CORE_DOC)
        for uri in AUTH_REDIRECT_URIS:
            self.assertIn(uri, CONTRACT)
        self.assertIn('export const AUTH_PATH = "/auth/google"', CONFIG_JS)
        self.assertIn('export const CLUSTER_PATH = "/api/cluster/status"', CONFIG_JS)
        self.assertIn('export const LOG_STREAM_PATH = "/api/logs/stream"', CONFIG_JS)
        self.assertIn(f"export const WORKER_PORT = {WORKER_PORT}", CONFIG_JS)
        self.assertIn(f"export const DASHBOARD_PORT = {DASHBOARD_PORT}", CONFIG_JS)
        self.assertIn("export const MAX_CHUNK_BYTES = 32 * 1024", CONFIG_JS)
        self.assertEqual(CHUNK_BYTES, 32 * 1024)
        self.assertIn('AUTH_PATH + "?mode=status"', OAUTH_JS)
        self.assertIn('mode === "start"', OAUTH_JS)
        self.assertIn('method: "POST"', OAUTH_JS)
        self.assertIn('AUTH_PATH + "?mode=logout"', OAUTH_JS)
        self.assertIn("redirect: \"manual\"", OAUTH_JS)
        self.assertIn("CLUSTER_PATH", NODE_PANEL_JS)
        self.assertIn('raw === "up" || raw === "down" || raw === "not_implemented"', NODES_JS)
        self.assertIn("found.latency_ms", NODES_JS)
        self.assertIn("LOG_STREAM_PATH", LOG_PANEL_JS)
        self.assertIn('Accept: "text/event-stream"', LOG_PANEL_JS)
        self.assertIn("data.lines", LOG_PANEL_JS)
        for path in ("/auth/google", "/api/cluster/status", "/api/logs/stream"):
            self.assertIn(path, CONTRACT)
            self.assertIn(path, CORE_DOC)
        for needle in (
            '"authenticated": false',
            '"authenticated": true',
            '"ok": true',
            '"role": "worker"',
            '"role": "dashboard"',
            "text/event-stream",
            "Cache-Control: no-cache",
            '"error": "offline"',
            '"detail": "database locked"',
            '"error": "not implemented"',
        ):
            self.assertIn(needle, CONTRACT)
            self.assertIn(needle, CORE_DOC)

    def test_dispatch_matches_the_shapes_the_page_reads(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = AuditLog(root / "audit.log")
            try:
                audit.write("info", "ready", ts="2026-11-10T17:00:00+07:00")
            finally:
                audit.close()
            ctx = GatewayContext(audit_path=root / "audit.log", probe=_up, session={})

            status = dispatch("GET", "/auth/google", {"mode": "status"}, ctx=ctx, accept="application/json")
            self.assertEqual(status["status"], 200)
            self.assertEqual(status["body"], {"authenticated": False})
            self.assertNotIn("location", status)
            self.assertIn("json", status["headers"]["Content-Type"])

            ctx.session = {"authenticated": True, "name": "Nammon", "email": "nammon1130@gmail.com"}
            signed = dispatch("GET", "/auth/google", {"mode": "status"}, ctx=ctx)
            self.assertEqual(signed["body"]["authenticated"], True)
            self.assertEqual(signed["body"]["name"], "Nammon")
            self.assertEqual(signed["body"]["email"], "nammon1130@gmail.com")
            ctx.session = {}

            started = dispatch(
                "GET",
                "/auth/google",
                {
                    "mode": "start",
                    "redirect_uri": "http://127.0.0.1:8421/auth/google",
                    "client_id": GOOGLE_CLIENT_ID,
                },
                ctx=ctx,
                accept="application/json",
            )
            self.assertEqual(started["status"], 200)
            self.assertTrue(started["body"]["url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?"))
            bad = dispatch(
                "GET",
                "/auth/google",
                {"mode": "start", "redirect_uri": "http://evil.test/auth/google"},
                ctx=ctx,
            )
            self.assertEqual(bad["status"], 400)

            logged_out = dispatch("POST", "/auth/google", {"mode": "logout"}, ctx=ctx)
            self.assertEqual(logged_out["status"], 200)
            self.assertEqual(logged_out["body"], {"ok": True})
            self.assertIn("SameSite=Lax", logged_out["headers"]["Set-Cookie"])

            cluster = dispatch("GET", "/api/cluster/status", ctx=ctx, accept="application/json")
            self.assertEqual(cluster["status"], 200)
            nodes = cluster["body"]["nodes"]
            self.assertEqual([(node["port"], node["role"]) for node in nodes], [(8420, "worker"), (8421, "dashboard")])
            for node in nodes:
                self.assertIn(node["status"], ("up", "down", "not_implemented"))
                self.assertTrue(node["latency_ms"] is None or isinstance(node["latency_ms"], int))

            sse = dispatch("GET", "/api/logs/stream", ctx=ctx, accept="text/event-stream")
            self.assertEqual(sse["status"], 200)
            self.assertEqual(sse["headers"]["Content-Type"], "text/event-stream")
            self.assertEqual(sse["headers"]["Cache-Control"], "no-cache")
            self.assertTrue(all(len(chunk) <= 32768 for chunk in sse["chunks"]))
            raw = b"".join(sse["chunks"]).decode("utf-8")
            self.assertIn("event: log\n", raw)
            data_line = next(line for line in raw.splitlines() if line.startswith("data: "))
            payload = json.loads(data_line[len("data: "):])
            self.assertEqual(set(payload), {"id", "ts", "level", "text"})
            self.assertEqual(payload["text"], "ready")

            snap = dispatch("GET", "/api/logs/stream", {"format": "json"}, ctx=ctx, accept="application/json")
            self.assertEqual(snap["status"], 200)
            self.assertEqual(snap["body"]["lines"][0]["text"], "ready")
            self.assertIn("json", snap["headers"]["Content-Type"])

            offline = dispatch("GET", "/api/logs/stream", ctx=GatewayContext(audit_path=root, probe=_up))
            self.assertEqual(offline["status"], 503)
            self.assertEqual(offline["body"], {"error": "offline", "detail": "database locked"})

            missing = dispatch("GET", "/api/health", ctx=ctx)
            self.assertEqual(missing["status"], 404)
            self.assertEqual(missing["body"], {"error": "not implemented"})

            options = dispatch("OPTIONS", "/api/logs/stream", ctx=ctx, origin="http://127.0.0.1:8421")
            self.assertEqual(options["status"], 204)
            self.assertEqual(options["headers"]["Access-Control-Allow-Origin"], "http://127.0.0.1:8421")

    def test_fastapi_snippet_names_the_same_three_routes(self):
        section = CORE_DOC.split("## Integration in app_server.py", 1)[1]
        for needle in (
            "FastAPI",
            "CORSMiddleware",
            "max_workers=2",
            "journal_mode=WAL",
            "GcHook",
            "get_executor()",
            '@app.api_route("/auth/google", methods=["GET", "POST", "OPTIONS"])',
            '@app.api_route("/api/cluster/status", methods=["GET", "OPTIONS"])',
            '@app.api_route("/api/logs/stream", methods=["GET", "OPTIONS"])',
            'RedirectResponse("/#/account", status_code=302)',
            "text/event-stream",
            "uvicorn.run",
        ):
            self.assertIn(needle, section)


if __name__ == "__main__":
    unittest.main()
