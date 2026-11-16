"""lca_core — pytest-compatible tests. No sockets and no listening ports.

Collected by pytest and by ``python -m unittest discover -s tests``.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lca_core import (  # noqa: E402
    CHUNK_BYTES,
    GATEWAY_ROUTES,
    DASHBOARD_PORT,
    WORKER_PORT,
    EventBus,
    GcHook,
    GatewayContext,
    McpEndpoint,
    OllamaClient,
    RagIndex,
    as_config,
    dispatch,
    get_executor,
    run_loop,
    shutdown_executor,
)
from lca_core.constants import (  # noqa: E402
    AUTH_REDIRECT_URIS,
    DASHBOARD_ORIGINS,
    GOOGLE_CLIENT_ID,
    LOG_BACKUPS,
    LOG_MAX_BYTES,
)
from lca_core.executor import submit  # noqa: E402
from lca_core.inference import OllamaOffline  # noqa: E402
from lca_core.logs import (  # noqa: E402
    AuditLog,
    close_log,
    format_sse,
    iter_sse_chunks,
    iter_tail_chunks,
    open_log,
    tail_records,
)
from lca_core.loop import TEMPLATES, render  # noqa: E402
from lca_core.roles import ROLES  # noqa: E402
from lca_core.router import cluster_status, default_registry, probe_node, tcp_probe  # noqa: E402
from lca_core.security import (  # noqa: E402
    client_id_allowed,
    cors_config,
    cors_headers,
    is_loopback_ip,
    origin_allowed,
    redirect_allowed,
)
from lca_core.storage import (  # noqa: E402
    checkpoint_and_close,
    cleanup_stale,
    connect,
    reclaim_wal,
    register,
    session,
)


def _up(host, port, timeout):
    return {"status": "up", "latency_ms": 3}


class LcaCoreIdleTest(unittest.TestCase):
    def test_constants_match_contract(self):
        self.assertEqual(CHUNK_BYTES, 32768)
        self.assertEqual(WORKER_PORT, 8420)
        self.assertEqual(DASHBOARD_PORT, 8421)
        self.assertEqual(GATEWAY_ROUTES, ("/auth/google", "/api/cluster/status", "/api/logs/stream"))
        self.assertEqual(DASHBOARD_ORIGINS, (
            "http://localhost:8421",
            "http://127.0.0.1:8421",
        ))

    def test_package_source_does_not_bind_or_serve(self):
        root = Path(__file__).resolve().parents[1]
        text = "\n".join(path.read_text(encoding="utf-8") for path in (root / "lca_core").glob("*.py"))
        self.assertNotIn("socket.bind", text)
        self.assertNotIn("uvicorn", text)
        self.assertNotIn(".listen(", text)
        self.assertNotIn("HTTPServer", text)
        self.assertFalse((root / "app_server.py").exists())
        self.assertFalse((root / "local_dashboard" / "server.py").exists())

    def test_import_does_not_require_a_server(self):
        repo = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [sys.executable, "-c", "import lca_core"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


class SecurityTest(unittest.TestCase):
    def test_origin_allowlist_is_exact(self):
        for origin in DASHBOARD_ORIGINS:
            self.assertTrue(origin_allowed(origin))
        for origin in ("*", "http://localhost:8421/", "http://127.0.0.1:8421/",
                       "https://localhost:8421", "http://localhost:8420",
                       "http://evil.test", "", None):
            self.assertFalse(origin_allowed(origin))

    def test_cors_config_has_no_wildcard(self):
        cfg = cors_config()
        self.assertEqual(cfg["allow_origins"], list(DASHBOARD_ORIGINS))
        self.assertNotIn("*", cfg["allow_origins"])
        self.assertNotIn("*", json.dumps(cfg))
        headers = cors_headers("http://localhost:8421")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://localhost:8421")
        self.assertIsNone(cors_headers("http://evil.test"))
        self.assertIsNone(cors_headers("*"))

    def test_redirect_and_client_id(self):
        for uri in AUTH_REDIRECT_URIS:
            self.assertTrue(redirect_allowed(uri))
        self.assertFalse(redirect_allowed("http://localhost:8421/auth/google/"))
        self.assertFalse(redirect_allowed("https://localhost:8421/auth/google"))
        self.assertTrue(client_id_allowed(None))
        self.assertTrue(client_id_allowed(""))
        self.assertTrue(client_id_allowed(GOOGLE_CLIENT_ID))
        self.assertFalse(client_id_allowed("other"))

    def test_loopback_filter(self):
        for value in ("127.0.0.1", "127.0.0.2", "::1", "localhost", "[::1]", "127.0.0.1:8421"):
            self.assertTrue(is_loopback_ip(value), value)
        for value in ("0.0.0.0", "192.168.1.10", "8.8.8.8", "", None, "localhost.evil.com", "10.0.0.1"):
            self.assertFalse(is_loopback_ip(value), value)


class RouterTest(unittest.TestCase):
    def tearDown(self):
        shutdown_executor(wait=True)

    def test_registry_roles(self):
        specs = default_registry()
        self.assertEqual([(item.port, item.role) for item in specs], [(8420, "worker"), (8421, "dashboard")])

    def test_primary_up_skips_fallback(self):
        calls = []

        def probe(host, port, timeout):
            calls.append((host, port))
            return {"status": "up", "latency_ms": 4}

        body = cluster_status(probe, timeout=0.2)
        self.assertEqual(calls, [("127.0.0.1", 8420), ("127.0.0.1", 8421)])
        self.assertEqual(body["nodes"][0]["status"], "up")
        self.assertEqual(body["nodes"][0]["latency_ms"], 4)
        self.assertEqual(body["nodes"][1]["role"], "dashboard")

    def test_primary_down_uses_fallback(self):
        def probe(host, port, timeout):
            if host == "127.0.0.1":
                raise OSError("refused")
            return {"status": "up", "latency_ms": 6}

        node = probe_node(default_registry()[0], probe, timeout=0.2)
        self.assertEqual(node["status"], "up")
        self.assertEqual(node["port"], 8420)
        self.assertEqual(node["latency_ms"], 6)

    def test_both_down(self):
        def probe(host, port, timeout):
            return {"status": "down", "latency_ms": 9}

        body = cluster_status(probe)
        self.assertEqual([node["status"] for node in body["nodes"]], ["down", "down"])
        self.assertEqual([node["latency_ms"] for node in body["nodes"]], [None, None])

    def test_not_implemented_does_not_fall_back(self):
        calls = []

        def probe(host, port, timeout):
            calls.append(host)
            return {"status": "not_implemented", "latency_ms": None}

        node = probe_node(default_registry()[1], probe)
        self.assertEqual(node["status"], "not_implemented")
        self.assertEqual(calls, ["127.0.0.1"])
        self.assertIsNone(node["latency_ms"])

    def test_executor_offload(self):
        body = cluster_status(_up, executor=get_executor(), timeout=0.2)
        self.assertEqual(len(body["nodes"]), 2)
        self.assertTrue(all(node["status"] == "up" for node in body["nodes"]))

    def test_tcp_probe_uses_injected_socket(self):
        class _Sock:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        with mock.patch("lca_core.router.socket.create_connection", return_value=_Sock()) as created:
            up = tcp_probe("127.0.0.1", 8420, 0.1)
        self.assertEqual(up["status"], "up")
        self.assertIsInstance(up["latency_ms"], int)
        created.assert_called_once_with(("127.0.0.1", 8420), timeout=0.1)

        with mock.patch("lca_core.router.socket.create_connection", side_effect=OSError("down")):
            down = tcp_probe("127.0.0.1", 8420, 0.1)
        self.assertEqual(down, {"status": "down", "latency_ms": None})


class BusTest(unittest.TestCase):
    def test_drop_oldest_and_topics(self):
        async def main():
            bus = EventBus(maxsize=2, overflow="drop-oldest")
            logs = bus.subscribe("logs")
            other = bus.subscribe("jobs")
            self.assertEqual(logs.maxsize, 2)
            self.assertEqual(await bus.publish_async("logs", "a"), 1)
            bus.publish("logs", "b")
            bus.publish("logs", "c")
            bus.publish("jobs", "z")
            self.assertEqual(logs.get_nowait(), "b")
            self.assertEqual(logs.get_nowait(), "c")
            self.assertEqual(other.get_nowait(), "z")
            self.assertEqual(bus.publish("missing", "x"), 0)

        asyncio.run(main())

    def test_reject_keeps_oldest(self):
        bus = EventBus(maxsize=1, overflow="reject")
        queue = bus.subscribe("logs")
        self.assertEqual(bus.publish("logs", {"n": 1}), 1)
        self.assertEqual(bus.publish("logs", {"n": 2}), 0)
        self.assertEqual(queue.get_nowait(), {"n": 1})

    def test_fanout_copies_dict(self):
        bus = EventBus(maxsize=2, overflow="reject")
        first = bus.subscribe("logs")
        second = bus.subscribe("logs")
        self.assertEqual(bus.publish("logs", {"n": 1}), 2)
        left = first.get_nowait()
        right = second.get_nowait()
        left["n"] = 9
        self.assertEqual(right["n"], 1)

    def test_unsubscribe_and_bad_overflow(self):
        bus = EventBus(maxsize=1)
        queue = bus.subscribe("logs")
        bus.unsubscribe("logs", queue)
        self.assertEqual(bus.publish("logs", "a"), 0)
        with self.assertRaises(ValueError):
            EventBus(maxsize=1, overflow="block")
        with self.assertRaises(ValueError):
            bus.subscribe("")


class LogsTest(unittest.TestCase):
    def test_rotating_handler_and_audit_counter(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rotated = root / "app.log"
            logger = open_log(rotated, max_bytes=80, backup_count=1, name="lca-test-rotate")
            try:
                self.assertEqual(logger.handlers[0].maxBytes, 80)
                self.assertEqual(logger.handlers[0].backupCount, 1)
                for _ in range(6):
                    logger.info("x" * 40)
                    logger.handlers[0].flush()
            finally:
                close_log(logger)
            self.assertTrue(Path(str(rotated) + ".1").exists())

            audit = AuditLog(root / "audit.log")
            try:
                self.assertEqual(audit._logger.handlers[0].maxBytes, LOG_MAX_BYTES)
                self.assertEqual(audit._logger.handlers[0].backupCount, LOG_BACKUPS)
                self.assertLessEqual(LOG_MAX_BYTES, 256 * 1024)
                ready = audit.write("info", "ready", ts="2026-11-10T17:00:00+07:00")
                audit.write("error", "disk full", ts="2026-11-10T17:00:01+07:00")
                self.assertEqual(audit.error_count, 1)
                self.assertEqual(ready["text"], "ready")
            finally:
                audit.close()

            records = tail_records(root / "audit.log")
            self.assertEqual(records[0]["level"], "info")
            self.assertEqual(records[1]["text"], "disk full")
            self.assertNotIn("<", records[0]["text"])

    def test_tail_and_sse_stay_within_32kb(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.log"
            payload = b"y" * 100_000
            path.write_bytes(payload)
            chunks = list(iter_tail_chunks(path, chunk_size=CHUNK_BYTES, max_bytes=100_000))
            self.assertTrue(chunks)
            self.assertTrue(all(len(chunk) <= 32768 for chunk in chunks))
            self.assertEqual(b"".join(chunks), payload)
            with self.assertRaises(ValueError):
                list(iter_tail_chunks(path, chunk_size=32769))

        record = {"id": 1, "ts": "2026-11-10T17:00:00+07:00", "level": "info", "text": "x" * 40000}
        framed = format_sse(record)
        pieces = list(iter_sse_chunks([record]))
        self.assertTrue(all(0 < len(piece) <= 32768 for piece in pieces))
        self.assertEqual(b"".join(pieces), framed)
        self.assertTrue(framed.startswith(b"event: log\ndata: "))

    def test_missing_file_and_locked_directory(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.log"
            self.assertEqual(tail_records(missing), [])
            with self.assertRaises(Exception) as caught:
                tail_records(Path(tmp))
            self.assertEqual(getattr(caught.exception, "detail", ""), "database locked")


class InferenceTest(unittest.TestCase):
    def test_offline_without_network(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            client = OllamaClient()
            self.assertEqual(client.health(), {"status": "ollama offline"})
            self.assertEqual(client.chat("qwen", []).status, "ollama offline")
            streamed = client.stream("qwen", [])
            self.assertEqual(streamed.status, "ollama offline")
            self.assertEqual(list(streamed.chunks), [])
        with self.assertRaises(RuntimeError):
            client.pull("qwen")
        with self.assertRaises(ValueError):
            OllamaClient(base_url="http://10.1.2.3:11434")

    def test_stream_chunks_and_chat_text(self):
        class _Body:
            def __init__(self, data: bytes):
                self.data = data
                self.sent = False
                self.closed = False

            def read(self, _n):
                if self.sent:
                    return b""
                self.sent = True
                return self.data

            def close(self):
                self.closed = True

        seen = []

        class _Transport:
            def open(self, method, url, body, timeout, headers):
                seen.append((method, url, body, timeout))
                if url.endswith("/api/version"):
                    return _Body(b"{}")
                raw = json.dumps({"message": {"content": "pong"}}).encode("utf-8")
                if body and body.get("stream"):
                    return _Body(b"z" * 50000)
                return _Body(raw)

        client = OllamaClient(transport=_Transport(), timeout=1.5)
        self.assertEqual(client.health()["status"], "up")
        chat = client.chat("qwen", [{"role": "user", "content": "hi"}], timeout=1.25)
        self.assertEqual(chat.status, "ok")
        self.assertEqual(chat.text, "pong")
        streamed = client.stream("qwen", [{"role": "user", "content": "hi"}])
        parts = list(streamed.chunks)
        self.assertEqual(streamed.status, "ok")
        self.assertTrue(all(len(part) <= 32768 for part in parts))
        self.assertEqual(b"".join(parts), b"z" * 50000)
        self.assertTrue(all(url.endswith("/api/chat") or url.endswith("/api/version") for _, url, _, _ in seen))
        self.assertNotIn("pull", " ".join(url for _, url, _, _ in seen))
        self.assertEqual(seen[1][3], 1.25)

    def test_transport_urlerror_is_offline(self):
        class _Transport:
            def open(self, *_args, **_kwargs):
                raise urllib.error.URLError("down")

        client = OllamaClient(transport=_Transport())
        self.assertEqual(client.chat("qwen", []).status, "ollama offline")
        self.assertIsInstance(OllamaOffline(), OllamaOffline)

    def test_allow_network_stays_on_loopback_and_is_patched(self):
        client = OllamaClient(allow_network=True, timeout=0.3)
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no")) as opener:
            self.assertEqual(client.health()["status"], "ollama offline")
        request = opener.call_args[0][0]
        self.assertTrue(request.full_url.startswith("http://127.0.0.1:11434/api/version"))
        self.assertEqual(opener.call_args.kwargs["timeout"], 0.3)


class StorageTest(unittest.TestCase):
    def test_pragmas_and_owned_cleanup(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "lca.db"
            conn = connect(db, busy_timeout_ms=5000)
            try:
                mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                sync = conn.execute("PRAGMA synchronous").fetchone()[0]
                busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
                self.assertEqual(str(mode).lower(), "wal")
                self.assertEqual(sync, 1)
                self.assertGreaterEqual(busy, 5000)
                conn.execute("PRAGMA wal_autocheckpoint=0;")
                conn.execute("CREATE TABLE t (x INTEGER)")
                conn.execute("INSERT INTO t VALUES (1)")
                conn.commit()
            finally:
                conn.close()
            had_wal = (Path(str(db) + "-wal").exists() or Path(str(db) + "-shm").exists())
            status = reclaim_wal(db)
            self.assertEqual(status, "checkpointed" if had_wal else "clean")
            self.assertEqual(reclaim_wal(root / "foreign.db"), "skipped")

            owned = root / "mine.db.tmp"
            owned.write_text("x", encoding="utf-8")
            register(owned)
            journal = root / "mine.db-journal"
            journal.write_text("j", encoding="utf-8")
            register(journal)
            foreign = root / "other.db.tmp"
            foreign.write_text("keep", encoding="utf-8")
            preview = cleanup_stale(root)
            self.assertTrue(preview["dry_run"])
            self.assertTrue(owned.exists())
            self.assertIn("mine.db.tmp", preview["matched"])
            self.assertIn("lca.db", preview["skipped"])
            applied = cleanup_stale(root, dry_run=False)
            self.assertEqual(sorted(applied["removed"]), ["mine.db-journal", "mine.db.tmp"])
            self.assertFalse(owned.exists())
            self.assertFalse(journal.exists())
            self.assertTrue(foreign.exists())
            self.assertTrue(db.exists())

            link = root / "link.db.tmp"
            link.symlink_to(foreign)
            register(link)
            skipped = cleanup_stale(root, dry_run=False)
            self.assertTrue(link.exists())
            self.assertIn("link.db.tmp", skipped["skipped"])
            self.assertTrue(foreign.exists())

    def test_session_removes_registered_temp_only(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "box.db"
            foreign = root / "other.db.tmp"
            foreign.write_text("keep", encoding="utf-8")
            with session(db) as conn:
                conn.execute("CREATE TABLE t (x INTEGER)")
                conn.commit()
                sibling = Path(str(db) + ".tmp")
                sibling.write_text("temp", encoding="utf-8")
                self.assertTrue(sibling.exists())
            self.assertFalse(Path(str(db) + ".tmp").exists())
            self.assertTrue(db.exists())
            self.assertTrue(foreign.exists())

    def test_static_web_root_is_refused(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            web = Path(tmp) / "local_dashboard" / "web"
            with self.assertRaises(ValueError):
                connect(web / "x.db")
            with self.assertRaises(ValueError):
                cleanup_stale(web)

    def test_checkpoint_and_close(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "a.db")
            checkpoint_and_close(conn)
            with self.assertRaises(Exception):
                conn.execute("SELECT 1")


class ExecutorAndLoopTest(unittest.TestCase):
    def tearDown(self):
        shutdown_executor(wait=True)

    def test_pool_is_two_workers(self):
        pool = get_executor()
        self.assertEqual(pool._max_workers, 2)
        self.assertEqual(submit(lambda a, b: a + b, 2, 3).result(timeout=5), 5)
        shutdown_executor(wait=True)
        self.assertIsNone(__import__("lca_core.executor", fromlist=["_executor"])._executor)

    def test_gc_hook_is_optional(self):
        calls = []
        hook = GcHook(interval_s=10, enabled=False, collect=lambda: calls.append(1))
        self.assertFalse(hook.maybe_collect(now=0))
        hook.enabled = True
        self.assertTrue(hook.maybe_collect(now=0))
        self.assertFalse(hook.maybe_collect(now=5))
        self.assertTrue(hook.maybe_collect(now=10))
        self.assertEqual(calls, [1, 1])
        with mock.patch("lca_core.executor.gc.collect", return_value=0) as collect:
            GcHook(interval_s=1, enabled=True).maybe_collect(now=1)
        collect.assert_called_once()

    def test_loop_goal_budget_and_hard_stop(self):
        for template in TEMPLATES.values():
            self.assertLess(len(template), 16)
        self.assertEqual(render("check"), "done?")

        def clock_factory():
            ticks = {"n": 0.0}

            def clock():
                ticks["n"] += 1.0
                return ticks["n"]

            return clock

        acted = []
        result = run_loop(
            lambda output: output == "done",
            lambda: "seen",
            lambda _obs: ("done", 2),
            lambda action: acted.append(action) or action,
            clock=clock_factory(),
            token_budget=10,
        )
        self.assertEqual(result.stop_reason, "goal")
        self.assertEqual(len(result.laps), 1)
        self.assertEqual(result.tokens_used, 2)
        self.assertEqual(result.laps[0].prompt, "next:1")
        self.assertGreater(result.laps[0].observe_ms, 0)
        self.assertEqual(acted, ["done"])

        acted.clear()
        stopped = run_loop(
            lambda _output: False,
            lambda: "seen",
            lambda _obs: ("go", 5),
            lambda action: acted.append(action),
            token_budget=3,
            clock=clock_factory(),
        )
        self.assertEqual(stopped.stop_reason, "token_budget")
        self.assertEqual(acted, [])
        self.assertFalse(stopped.laps[0].acted)

        hard = run_loop(
            lambda _output: False,
            lambda: None,
            lambda _obs: ("x", 0),
            lambda _action: None,
            hard_stop=lambda: True,
        )
        self.assertEqual(hard.stop_reason, "hard_stop")
        self.assertEqual(hard.laps, [])

        flags = {"n": 0}

        def flip():
            flags["n"] += 1
            return flags["n"] >= 2

        after = run_loop(
            lambda _output: False,
            lambda: None,
            lambda _obs: ("x", 1),
            lambda _action: "ran",
            hard_stop=flip,
            max_laps=10,
        )
        self.assertEqual(after.stop_reason, "hard_stop")
        self.assertEqual(len(after.laps), 1)

        counted = {"n": 0}

        def observe():
            counted["n"] += 1
            return counted["n"]

        capped = run_loop(
            lambda _output: False,
            observe,
            lambda _obs: ("x", 0),
            lambda _action: None,
            max_laps=50,
        )
        self.assertEqual(capped.stop_reason, "max_laps")
        self.assertEqual(len(capped.laps), 10)
        self.assertEqual(counted["n"], 10)


class RolesAndStubsTest(unittest.TestCase):
    def test_roles_are_local_config(self):
        config = as_config()
        self.assertEqual(set(config), set(ROLES))
        self.assertEqual(config["9arm_manager"]["duty"], "orchestrator/governor")
        self.assertEqual(config["new_bot"]["title"], "New Bot")
        self.assertEqual(config["uol_bot"]["title"], "UOL Bot")
        self.assertEqual(config["q_botdata"]["title"], "Q Botdata")
        self.assertEqual(config["amd_bot"]["duty"], "CPU/thread pool")
        self.assertEqual(config["ulo_bot"]["duty"], "local file sync + workspace integrity")
        self.assertEqual(config["moon_bot"]["title"], "Moon Bot")
        self.assertEqual(config["bot_trading"]["title"], "Bot trading")
        blob = json.dumps(config)
        self.assertNotIn("http://", blob)
        self.assertNotIn("https://", blob)
        for item in config.values():
            self.assertFalse(item["network"])
            self.assertTrue(all(name.startswith("lca_core.") for name in item["modules"]))
        self.assertIn("does not submit orders", config["bot_trading"]["notes"])

    def test_stubs_do_not_run(self):
        with self.assertRaises(NotImplementedError):
            RagIndex().add("a", "b")
        with self.assertRaises(NotImplementedError):
            RagIndex().query("b")
        with self.assertRaises(NotImplementedError):
            McpEndpoint().list_tools()
        with self.assertRaises(NotImplementedError):
            McpEndpoint().call_tool("n", {})


class DispatchTest(unittest.TestCase):
    def tearDown(self):
        shutdown_executor(wait=True)

    def _ctx(self, root: Path, **kwargs) -> GatewayContext:
        params = {
            "audit_path": root / "audit.log",
            "probe": _up,
            "session": {},
        }
        params.update(kwargs)
        return GatewayContext(**params)

    def test_auth_status_start_and_logout(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._ctx(Path(tmp), session={"authenticated": False})
            status = dispatch("GET", "/auth/google", {"mode": "status"}, ctx=ctx)
            self.assertEqual(status["status"], 200)
            self.assertEqual(status["body"], {"authenticated": False})
            self.assertNotIn("location", status)

            ctx.session = {"authenticated": True, "name": "Nammon", "email": "nammon1130@gmail.com"}
            signed = dispatch("GET", "/auth/google", {"mode": "status"}, ctx=ctx)
            self.assertEqual(signed["body"]["name"], "Nammon")
            self.assertEqual(signed["body"]["authenticated"], True)

            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
                bad = dispatch(
                    "GET",
                    "/auth/google",
                    {"mode": "start", "redirect_uri": "https://evil.test/auth/google"},
                    ctx=ctx,
                )
                self.assertEqual(bad["status"], 400)
                started = dispatch(
                    "GET",
                    "/auth/google",
                    {
                        "mode": "start",
                        "redirect_uri": "http://127.0.0.1:8421/auth/google",
                        "client_id": GOOGLE_CLIENT_ID,
                    },
                    ctx=ctx,
                )
            self.assertEqual(started["status"], 200)
            self.assertIn("https://accounts.google.com/o/oauth2/v2/auth?", started["body"]["url"])
            self.assertIn("redirect_uri=http%3A%2F%2F127.0.0.1%3A8421%2Fauth%2Fgoogle", started["body"]["url"])
            self.assertNotIn("client_secret", started["body"]["url"])

            mismatch = dispatch(
                "GET",
                "/auth/google",
                {
                    "mode": "start",
                    "redirect_uri": "http://127.0.0.1:8421/auth/google",
                    "client_id": "nope",
                },
                ctx=ctx,
            )
            self.assertEqual(mismatch["status"], 400)

            ctx.expected_state = "state-1"
            rejected = dispatch("GET", "/auth/google", {"code": "abc", "state": "no"}, ctx=ctx)
            self.assertEqual(rejected["status"], 400)
            accepted = dispatch("GET", "/auth/google", {"code": "abc", "state": "state-1"}, ctx=ctx)
            self.assertEqual(accepted["location"], "/#/account")
            self.assertNotIn("abc", json.dumps(accepted["body"]))

            logged_out = dispatch("POST", "/auth/google", {"mode": "logout"}, ctx=ctx)
            self.assertEqual(logged_out["status"], 200)
            self.assertEqual(logged_out["body"], {"ok": True})
            self.assertIn("Max-Age=0", logged_out["headers"]["Set-Cookie"])
            self.assertIn("SameSite=Lax", logged_out["headers"]["Set-Cookie"])

    def test_cluster_and_logs_routes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = AuditLog(root / "audit.log")
            try:
                audit.write("info", "ready", ts="2026-11-10T17:00:00+07:00")
            finally:
                audit.close()
            ctx = self._ctx(root, executor=get_executor())
            cluster = dispatch("GET", "/api/cluster/status", ctx=ctx)
            self.assertEqual(cluster["status"], 200)
            self.assertEqual(
                [(node["port"], node["role"]) for node in cluster["body"]["nodes"]],
                [(8420, "worker"), (8421, "dashboard")],
            )
            sse = dispatch("GET", "/api/logs/stream", ctx=ctx, accept="text/event-stream")
            self.assertEqual(sse["headers"]["Content-Type"], "text/event-stream")
            self.assertEqual(sse["headers"]["Cache-Control"], "no-cache")
            self.assertTrue(sse["chunks"])
            self.assertTrue(all(len(chunk) <= 32768 for chunk in sse["chunks"]))
            self.assertIn(b"ready", b"".join(sse["chunks"]))

            snap = dispatch("GET", "/api/logs/stream", {"format": "json"}, ctx=ctx)
            self.assertEqual(snap["body"]["lines"][0]["text"], "ready")

            missing = self._ctx(root, audit_path=root)
            offline = dispatch("GET", "/api/logs/stream", ctx=missing)
            self.assertEqual(offline["status"], 503)
            self.assertEqual(offline["body"]["error"], "offline")
            self.assertEqual(offline["body"]["detail"], "database locked")

            unknown = dispatch("GET", "/api/health", ctx=ctx)
            self.assertEqual(unknown["status"], 404)
            self.assertEqual(unknown["body"], {"error": "not implemented"})

    def test_cors_on_dispatch(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._ctx(Path(tmp))
            allowed = dispatch(
                "OPTIONS",
                "/api/cluster/status",
                ctx=ctx,
                origin="http://127.0.0.1:8421",
            )
            self.assertEqual(allowed["status"], 204)
            self.assertEqual(
                allowed["headers"]["Access-Control-Allow-Origin"],
                "http://127.0.0.1:8421",
            )
            refused = dispatch("OPTIONS", "/api/logs/stream", ctx=ctx, origin="https://evil.test")
            self.assertEqual(refused["status"], 403)
            self.assertNotIn("Access-Control-Allow-Origin", refused["headers"])
            quiet = dispatch("GET", "/auth/google", {"mode": "status"}, ctx=ctx, origin="https://evil.test")
            self.assertNotIn("Access-Control-Allow-Origin", quiet["headers"])
            echoed = dispatch(
                "GET",
                "/auth/google",
                {"mode": "status"},
                ctx=ctx,
                origin="http://localhost:8421",
            )
            self.assertEqual(echoed["headers"]["Access-Control-Allow-Origin"], "http://localhost:8421")


if __name__ == "__main__":
    unittest.main()
