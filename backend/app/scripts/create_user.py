"""Create exactly the protected ai360 ROOT account."""

from __future__ import annotations

import argparse
import getpass
import os
import sys

import bcrypt

from app.auth.models import UserRecord
from app.auth.passwords import hash_password
from app.auth.repositories import AdminAlreadyExistsError
from app.auth.runtime import AuthRuntime, get_auth_runtime


def bootstrap_admin(
    *,
    username: str,
    password: str,
    runtime: AuthRuntime,
) -> UserRecord:
    password_hash = (
        bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        if username == password == "ai360"
        else hash_password(password)
    )
    return runtime.users.create_root(
        username=username,
        password_hash=password_hash,
    )


def _read_password(environment_name: str) -> str:
    from_environment = os.environ.get(environment_name)
    if from_environment is not None:
        return from_environment
    if sys.stdin.isatty():
        return getpass.getpass("Admin password: ")
    raise RuntimeError(
        f"set {environment_name} or run interactively to provide the password"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create the protected openVman ai360 ROOT",
    )
    parser.add_argument("--username", choices=["ai360"], default="ai360")
    parser.add_argument(
        "--password-env",
        default="BOOTSTRAP_ADMIN_PASSWORD",
        help="environment variable containing the initial ROOT password",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        user = bootstrap_admin(
            username=args.username,
            password=_read_password(args.password_env),
            runtime=get_auth_runtime(),
        )
    except (AdminAlreadyExistsError, RuntimeError, ValueError) as exc:
        print(f"bootstrap failed: {exc}", file=sys.stderr)
        return 1

    print(f"created ROOT {user.username} ({user.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
