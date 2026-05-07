"""Manage public embed API keys."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TextIO

from app.gateway.embed_keys import EmbedKeyRecord, EmbedKeyStore


def _record_to_dict(record: EmbedKeyRecord) -> dict:
    return asdict(record)


def _write_json(stdout: TextIO, payload: dict) -> None:
    stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    stdout.write("\n")


def _find_record(store: EmbedKeyStore, key_id: str) -> EmbedKeyRecord | None:
    return next((record for record in store.list() if record.key_id == key_id), None)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage public embed API keys.")
    parser.add_argument(
        "--store",
        default=None,
        help="Path to embed key store JSON. Defaults to backend/data/embed_keys.json.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a new embed API key.")
    create.add_argument("--tenant-id", required=True)
    create.add_argument("--domain", action="append", required=True, dest="domains")
    create.add_argument("--note", default="")

    subparsers.add_parser("list", help="List stored keys without plaintext secrets.")

    disable = subparsers.add_parser("disable", help="Disable a key by id.")
    disable.add_argument("key_id")

    rotate = subparsers.add_parser("rotate", help="Disable a key and create a replacement.")
    rotate.add_argument("key_id")
    rotate.add_argument("--note", default=None)

    return parser


def main(argv: list[str] | None = None, *, stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    store_path = Path(args.store) if args.store else None
    store = EmbedKeyStore(store_path) if store_path is not None else EmbedKeyStore()

    if args.command == "create":
        created = store.create(
            tenant_id=args.tenant_id,
            allowed_domains=args.domains,
            note=args.note,
        )
        payload = {
            **_record_to_dict(created.record),
            "secret": created.secret,
        }
        _write_json(stdout, payload)
        return 0

    if args.command == "list":
        _write_json(stdout, {"keys": [_record_to_dict(record) for record in store.list()]})
        return 0

    if args.command == "disable":
        disabled = store.disable(args.key_id)
        _write_json(stdout, {"key_id": args.key_id, "disabled": disabled is not None})
        return 0 if disabled is not None else 1

    if args.command == "rotate":
        existing = _find_record(store, args.key_id)
        if existing is None:
            stderr.write(f"key not found: {args.key_id}\n")
            return 1
        if store.disable(args.key_id) is None:
            stderr.write(f"key not disabled: {args.key_id}\n")
            return 1
        created = store.create(
            tenant_id=existing.tenant_id,
            allowed_domains=existing.allowed_domains,
            note=existing.note if args.note is None else args.note,
        )
        payload = {
            **_record_to_dict(created.record),
            "old_key_id": args.key_id,
            "secret": created.secret,
        }
        _write_json(stdout, payload)
        return 0

    parser.print_help(stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
