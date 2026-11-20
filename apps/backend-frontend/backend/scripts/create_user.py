"""Create a user from the command line. The password is read without echo, never from argv.

Usage:  python -m scripts.create_user <username> [--admin]
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import create_user  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.errors import AppError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a backend-frontend user")
    parser.add_argument("username")
    parser.add_argument("--admin", action="store_true", help="give the user the admin role")
    args = parser.parse_args(argv)
    password = getpass.getpass("Password (10+ characters): ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match", file=sys.stderr)
        return 1
    settings = load_settings()
    try:
        user = create_user(Database(settings.data_dir / "app.db"), args.username, password,
                           "admin" if args.admin else "user")
    except AppError as err:
        print(err.user_message, file=sys.stderr)
        return 1
    print(f"created {user.username} ({user.role})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
