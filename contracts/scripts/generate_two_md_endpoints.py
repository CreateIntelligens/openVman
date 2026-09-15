#!/usr/bin/env python3
"""Generate the TypeScript and Brain Python views of the 2MD endpoint contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "contracts" / "two-md-endpoints.json"
TS_OUTPUT = ROOT / "contracts" / "two-md-endpoints.ts"
PY_OUTPUT = ROOT / "brain" / "api" / "core" / "two_md_defaults.py"


def _load_urls() -> list[str]:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    urls = payload.get("base_urls") if isinstance(payload, dict) else None
    if not isinstance(urls, list) or not urls or not all(isinstance(url, str) and url for url in urls):
        raise ValueError("contracts/two-md-endpoints.json.base_urls must be a non-empty string array")
    if len(set(urls)) != len(urls):
        raise ValueError("2MD endpoint list must not contain duplicates")
    return urls


def _render_ts(urls: list[str]) -> str:
    entries = "\n".join(f"  '{url}'," for url in urls)
    return (
        "/** Generated from contracts/two-md-endpoints.json. */\n"
        "export const TWO_MD_BASE_URLS = [\n"
        f"{entries}\n"
        "] as const;\n"
    )


def _render_py(urls: list[str]) -> str:
    entries = "\n".join(f'    "{url}",' for url in urls)
    return (
        '"""Generated 2MD endpoint defaults. Source: contracts/two-md-endpoints.json."""\n\n'
        "from __future__ import annotations\n\n"
        "TWO_MD_BASE_URLS: tuple[str, ...] = (\n"
        f"{entries}\n"
        ")\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    urls = _load_urls()
    expected = {TS_OUTPUT: _render_ts(urls), PY_OUTPUT: _render_py(urls)}
    mismatches = [str(path) for path, content in expected.items() if not path.exists() or path.read_text(encoding="utf-8") != content]
    if args.check:
        if mismatches:
            print("stale generated files:")
            print("\n".join(mismatches))
            return 1
        return 0
    for path, content in expected.items():
        path.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
