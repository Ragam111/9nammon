r"""lca_admin_app.py — LCA-Admin.exe: the owner/staff console, split from the customer app.

- edition "admin": the only build that contains /admin, /admin/db, /console*, /dev
- bind 127.0.0.1 only (no --host), default port 8430 (never 8420/8422)
- every request must come from this machine: proxy headers or a live tunnel → 403
- same data_dir() as LCA-Desktop, so keys made here work in the customer app
- the window opens /admin (title "LCA Admin"); a CEO signs in with a real account

Build (Windows):
  python scripts/stage_app.py --edition admin --out build/app_admin
  pyinstaller --onefile --windowed --name LCA-Admin ^
    --add-data "build/app_admin;app" --add-data "sysmanager;sysmanager" ^
    --add-data "local_coder.py;." --add-data "VERSION;." --add-data "scripts/node_ctl.py;scripts" ^
    lca_admin_app.py
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402
from lca_app import data_dir, launch_url, open_app_window  # noqa: E402,F401  (shared data dir)

EDITION = "admin"
DEFAULT_PORT = 8430
HOST = "127.0.0.1"
FORBIDDEN_PORTS = frozenset({8420, 8422})
START_PATH = "/admin"
WINDOW_TITLE = "LCA Admin"


def build_server(root, preferred_port: int = DEFAULT_PORT, host: str = HOST,
                 edition: str = EDITION):
    """Admin HTTP server on loopback only — returns (httpd, port).
    Raises ValueError for a non-loopback host or a non-admin edition."""
    if host != HOST:
        raise ValueError("LCA-Admin bind 127.0.0.1 เท่านั้น")
    if edition != EDITION:
        raise ValueError("LCA-Admin ต้องเป็น edition admin")
    port = _pick_port(preferred_port, host)
    handler = server.make_handler(Path(root), None, bind_host=host, edition=edition)
    httpd = server.ExclusiveHTTPServer((host, port), handler)
    httpd.lca_session_token = handler.session_token
    httpd.lca_session_auto = handler.session_token_auto
    httpd.lca_edition = edition
    return httpd, httpd.server_address[1]


def _pick_port(preferred: int, host: str) -> int:
    """Free port near preferred, skipping the customer/cluster ports."""
    port = server.find_free_port(preferred, host=host)
    while port in FORBIDDEN_PORTS:
        port = server.find_free_port(port + 1, host=host)
    return port


def main() -> int:
    parser = argparse.ArgumentParser(prog="LCA-Admin", description="LCA Admin — owner console")
    parser.add_argument("--version", action="version",
                        version=f"LCA Admin {server.read_version()}")
    parser.parse_args()
    root = data_dir()
    server.org_store.init_storage(root)
    server.session_store.configure(root)
    httpd, port = build_server(root)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    print(f"[{WINDOW_TITLE}] http://{HOST}:{port}{START_PATH}  (data: {root})")
    time.sleep(1)
    open_app_window(launch_url(port, START_PATH))
    try:
        while t.is_alive():
            t.join(timeout=3600)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
