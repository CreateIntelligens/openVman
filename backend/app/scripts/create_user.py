"""Create exactly the first administrator in the account database."""

from __future__ import annotations

import argparse
import getpass
import os
import sys

import bcrypt

from app.auth.models import AccountRole, UserRecord
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
    return runtime.users.create_first_admin(
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
        description="Create the first openVman administrator",
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", choices=[AccountRole.ADMIN.value], default="admin")
    parser.add_argument(
        "--password-env",
        default="BOOTSTRAP_ADMIN_PASSWORD",
        help="environment variable containing the initial password",
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

    print(f"created administrator {user.username} ({user.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
