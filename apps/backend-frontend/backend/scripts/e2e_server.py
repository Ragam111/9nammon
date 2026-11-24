"""API server for the Playwright E2E run: fresh data dir, fake model, one admin user.

Reads E2E_PASSWORD (set by playwright.config.ts for each run) and, optionally,
E2E_API_PORT / E2E_MODEL_PORT / E2E_DATA_DIR. Never use this for a real deployment.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def main() -> None:
    password = os.environ.get("E2E_PASSWORD", "")
    if len(password) < 10:
        sys.exit("E2E_PASSWORD (10+ chars) must be set by the test runner")
    data_dir = Path(os.environ.get("E2E_DATA_DIR") or tempfile.mkdtemp(prefix="bf-e2e-"))
    shutil.rmtree(data_dir, ignore_errors=True)  # every run starts empty
    os.environ.update({
        "DATA_DIR": str(data_dir),
        "MODEL_BASE_URL": f"http://127.0.0.1:{os.environ.get('E2E_MODEL_PORT', '9101')}/v1",
        "MODEL_NAME": "fake-model",
        "MODEL_API_KEY": "",
        "MODEL_TIMEOUT_S": "15",
        "ENV_FILE": str(data_dir / "no.env"),  # ignore any developer .env
        "CORS_ORIGINS": "http://127.0.0.1:5174,http://localhost:5174",
        # One run makes many logins and page loads from 127.0.0.1; the production limits make it flaky.
        "LOGIN_PER_IP_PER_MIN": "1000",
        "LOGIN_PER_USER_PER_MIN": "1000",
        "RATE_LIMIT_IP_PER_MIN": "10000",
        "RATE_LIMIT_USER_PER_MIN": "10000",
    })
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    from app.auth import create_user
    from app.db import Database

    create_user(Database(data_dir / "app.db"), "e2e-admin", password, "admin")
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("E2E_API_PORT", "8011")), log_level="warning")


if __name__ == "__main__":
    main()
