"""Run the API for local development against the fake model (scripts/fake_model.py on port 9100).

Usage: python scripts/dev_server.py
Values already set in the environment or in .env win over these dev defaults.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
DEV_PORT = 8010  # the Vite dev proxy forwards /api here (8000 is often taken by other local stacks)

DEV_DEFAULTS = {
    "MODEL_BASE_URL": "http://127.0.0.1:9100/v1",
    "MODEL_NAME": "fake-model",
    "DATA_DIR": str(BACKEND / "data-dev"),
    "MODEL_TIMEOUT_S": "20",
}


def main() -> None:
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    for name, value in DEV_DEFAULTS.items():
        os.environ.setdefault(name, value)
    import uvicorn  # imported after the environment is set

    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("PORT", str(DEV_PORT))))


if __name__ == "__main__":
    main()
