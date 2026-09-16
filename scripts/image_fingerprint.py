"""Fingerprint committed Docker build inputs before reusing a published image."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path, PurePosixPath

COMMON_INPUTS: tuple[str, ...] = (
    ".github/workflows/docker-publish.yml",
    "scripts/image_fingerprint.py",
)


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True
    )


def instructions(dockerfile: str) -> list[tuple[str, str]]:
    """Reject unsupported input syntax instead of silently omitting sources."""
    result = []
    pending = ""
    for line in dockerfile.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            if line.lower().startswith("# escape=") and line[9:] != "\\":
                raise ValueError("Only Docker's default escape is supported")
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        line = pending + line
        pending = ""
        parts = line.split(maxsplit=1)
        operation = parts[0]
        value = parts[1] if len(parts) == 2 else ""
        if "<<" in value:
            raise ValueError("Dockerfile heredocs require explicit input support")
        result.append((operation.upper(), value.strip()))
    if pending:
        raise ValueError("Unterminated Dockerfile continuation")
    return result


def copy_sources(dockerfile: str) -> list[str]:
    sources = []
    for operation, value in instructions(dockerfile):
        if operation == "RUN" and "--mount=" in value:
            # A bind mount reads the build context just like COPY does. Current
            # Dockerfiles only use cache mounts; require explicit support first.
            for mount in re.findall(r"--mount=([^\s]+)", value):
                if not mount.startswith(("type=cache,", "type=secret,", "type=ssh,")):
                    raise ValueError("Unsupported RUN mount input: " + mount)
        if operation not in {"COPY", "ADD"}:
            continue
        from_stage = False
        while value.startswith("--"):
            flag, separator, value = value.partition(" ")
            if not separator or "=" not in flag:
                raise ValueError("Unsupported COPY/ADD flag: " + flag)
            if flag.startswith("--from="):
                from_stage = True
            elif not flag.startswith(("--chown=", "--chmod=", "--exclude=")):
                raise ValueError("Unsupported COPY/ADD flag: " + flag)
            value = value.lstrip()
        parts = json.loads(value) if value.startswith("[") else shlex.split(value)
        if not isinstance(parts, list) or len(parts) < 2:
            raise ValueError("COPY/ADD requires sources and a destination")
        if from_stage:
            continue
        for source in parts[:-1]:
            if not isinstance(source, str) or "$" in source or "://" in source:
                raise ValueError("Unsupported COPY/ADD source: " + repr(source))
            if ".." in PurePosixPath(source).parts:
                raise ValueError("COPY/ADD source traverses context: " + source)
            sources.append(source.removeprefix("./").strip("/") or ".")
    return sources


def fingerprint(
    repo: Path,
    context: str,
    dockerfile: str,
    *,
    base_only: bool = False,
    base_digest: str = "",
) -> tuple[str, list[str]]:
    context = context.removeprefix("./").rstrip("/")
    dockerfile = dockerfile.removeprefix("./")
    content = git(repo, "show", "HEAD:" + dockerfile)
    if base_only:
        prefix, count = re.subn(
            r"(?m)^FROM \$\{BASE_IMAGE\}.*\Z", "", content,
            flags=re.DOTALL,
        )
        if count != 1:
            raise ValueError("Expected exactly one FROM ${BASE_IMAGE} boundary")
        content = prefix
    sources = copy_sources(content)
    tracked = {}
    for item in git(repo, "ls-tree", "-rz", "HEAD").split("\0"):
        if item:
            metadata, path = item.split("\t", 1)
            mode, kind, object_id = metadata.split()
            if kind != "blob":
                raise ValueError("Unsupported non-file build input: " + path)
            tracked[path] = (mode, object_id)

    prefix = "" if context == "." else context + "/"
    selected = set(COMMON_INPUTS)
    selected.update((prefix + ".dockerignore", dockerfile + ".dockerignore"))
    for source in sources:
        matched = False
        for path in tracked:
            if not path.startswith(prefix):
                continue
            relative = path[len(prefix):]
            # Match source directories as well as wildcard filenames. Including
            # ignored files is conservative: it can rebuild, never reuse stale data.
            candidates = [relative, *map(str, PurePosixPath(relative).parents)]
            if source == "." or any(
                fnmatch.fnmatchcase(candidate, source) for candidate in candidates
            ):
                selected.add(path)
                matched = True
        if not matched:
            raise ValueError("COPY/ADD source has no committed files: " + source)

    entries = [(path, tracked.get(path)) for path in sorted(selected)]
    payload = [context, dockerfile, content, base_only, base_digest, entries]
    digest = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    return digest, sorted(selected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--dockerfile", required=True)
    parser.add_argument("--base-only", action="store_true")
    parser.add_argument("--base-digest", default="")
    args = parser.parse_args()
    digest, paths = fingerprint(
        Path.cwd(), args.context, args.dockerfile,
        base_only=args.base_only, base_digest=args.base_digest,
    )
    print(f"Build inputs: {len(paths)} tracked paths; fingerprint={digest}", file=sys.stderr)
    print(digest)


if __name__ == "__main__":
    main()
