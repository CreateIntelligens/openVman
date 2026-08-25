"""Container-local ROOT password recovery without credential output."""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from app.auth.passwords import PasswordValidationError, hash_password
from app.auth.repositories import RepositoryError
from app.auth.runtime import get_auth_runtime


def _read_password(environment_name: str) -> str:
    value = os.environ.get(environment_name)
    if value is not None:
        return value
    if sys.stdin.isatty():
        return getpass.getpass("New ROOT password: ")
    raise RuntimeError(
        f"set {environment_name} or run interactively to provide the password"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recover the existing ai360 ROOT password",
    )
    parser.add_argument(
        "--password-env",
        default="ROOT_RECOVERY_PASSWORD",
        help="environment variable containing the replacement password",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        password_hash = hash_password(_read_password(args.password_env))
        root = get_auth_runtime().users.recover_root_password(
            password_hash=password_hash,
        )
    except (PasswordValidationError, RepositoryError, RuntimeError) as exc:
        print(f"ROOT recovery failed: {exc}", file=sys.stderr)
        return 1
    print(f"ROOT password replaced for {root.username} ({root.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
