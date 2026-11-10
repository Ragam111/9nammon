"""Shared limits for the 8GB localhost dashboard.

Nothing here opens a socket. Product VERSION stays in the repo ``VERSION`` file.
"""

from __future__ import annotations

WORKER_PORT = 8420
DASHBOARD_PORT = 8421

DASHBOARD_ORIGINS = (
    "http://localhost:8421",
    "http://127.0.0.1:8421",
)

AUTH_REDIRECT_URIS = (
    "http://localhost:8421/auth/google",
    "http://127.0.0.1:8421/auth/google",
)

# Public OAuth client id from the dashboard page. Not a secret.
GOOGLE_CLIENT_ID = (
    "456424591178-g3ufhccbhmnvt74ne7hfq27432b3sm19.apps.googleusercontent.com"
)

OLLAMA_URL = "http://127.0.0.1:11434"

# Socket writes and file reads for /api/logs/stream and Ollama streaming.
CHUNK_BYTES = 32768

POOL_WORKERS = 2
DEFAULT_MAX_LAPS = 10
HARD_LAP_CAP = 10

# Small on purpose: HDD box, 8GB RAM, do not grow multi-megabyte log buffers.
LOG_MAX_BYTES = 256 * 1024
LOG_BACKUPS = 2

QUEUE_MAXSIZE = 32
PROBE_TIMEOUT_S = 0.4
OLLAMA_TIMEOUT_S = 5.0
BUSY_TIMEOUT_MS = 5000
