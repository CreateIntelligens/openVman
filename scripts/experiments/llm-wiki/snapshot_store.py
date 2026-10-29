"""Publish complete experiment generations through one atomic current link."""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import uuid

from experiment_io import validate_output


MANIFEST = "manifest.json"
GENERATION = re.compile(r"[0-9a-f]{32}")


def _root(path):
    original = Path(os.path.abspath(path))
    for parent in (original, *original.parents):
        if parent.is_symlink():
            raise ValueError("Snapshot root cannot traverse symlinks")
    return validate_output(original)


def _relative_name(name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("File keys must be relative POSIX paths")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Noncanonical file key")
    if PurePosixPath(name).is_absolute() or "\x00" in name:
        raise ValueError("Invalid relative file key")
    if parts[0] == MANIFEST:
        raise ValueError("manifest.json is reserved")
    return name


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_file(path, content):
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def _writer_lock(root):
    descriptor = os.open(
        root / ".publish.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Snapshot lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _regular_bytes(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Snapshot contains a nonregular file")
        return stream.read()


def _validate_generation(directory, snapshot_id):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Generation must be a real directory")
    try:
        metadata = json.loads(_regular_bytes(directory / MANIFEST))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Missing or invalid snapshot manifest") from exc
    if (
        not isinstance(metadata, dict)
        or metadata.get("version") != 1
        or metadata.get("snapshot_id") != snapshot_id
        or not isinstance(metadata.get("files"), dict)
        or not isinstance(metadata.get("source_manifest"), dict)
    ):
        raise ValueError("Invalid snapshot manifest schema")
    expected = set(metadata["files"]) | {MANIFEST}
    actual = set()
    for parent, directories, filenames in os.walk(directory, followlinks=False):
        for name in directories:
            if (Path(parent) / name).is_symlink():
                raise ValueError("Snapshot directories cannot be symlinks")
        for name in filenames:
            target = Path(parent) / name
            if not stat.S_ISREG(target.lstat().st_mode):
                raise ValueError("Snapshot files must be regular files")
            actual.add(target.relative_to(directory).as_posix())
    if actual != expected:
        raise ValueError("Snapshot file set differs from its manifest")
    for name, record in metadata["files"].items():
        _relative_name(name)
        if not isinstance(record, dict):
            raise ValueError("Invalid snapshot file record")
        content = _regular_bytes(directory / name)
        if (
            record.get("sha256") != hashlib.sha256(content).hexdigest()
            or record.get("size") != len(content)
        ):
            raise ValueError(f"Snapshot integrity failure: {name}")
    return metadata


def _open(root):
    current = root / "current"
    if not current.is_symlink():
        raise ValueError("Snapshot current must be a symlink")
    target = os.readlink(current)
    parts = target.split("/")
    if len(parts) != 2 or parts[0] != "generations" or not GENERATION.fullmatch(parts[1]):
        raise ValueError("Current must reference a relative generation")
    generations = root / "generations"
    if generations.is_symlink() or not generations.is_dir():
        raise ValueError("Generations must be a real directory")
    directory = generations / parts[1]
    _validate_generation(directory, parts[1])
    return directory


def open_snapshot(root: Path) -> Path:
    """Resolve current once, verify all payload hashes, return that generation."""
    return _open(_root(root))


def _switch_current(root, snapshot_id):
    temporary = root / f".current-{uuid.uuid4().hex}"
    try:
        temporary.symlink_to(f"generations/{snapshot_id}")
        os.replace(temporary, root / "current")
    finally:
        if temporary.is_symlink():
            temporary.unlink()


def publish_snapshot(
    root: Path,
    files: dict[str, bytes | str],
    source_manifest: dict,
) -> str:
    """Publish a complete immutable generation; failed writes preserve current.

    Payload keys are canonical relative POSIX paths. ``manifest.json`` is
    reserved; it records every payload hash and a copy of source_manifest.
    Readers must retain the returned generation path from open_snapshot.
    """
    root = _root(root)
    if not isinstance(files, dict) or not isinstance(source_manifest, dict):
        raise ValueError("files and source_manifest must be dictionaries")
    payload = {}
    for name, content in files.items():
        name = _relative_name(name)
        if not isinstance(content, (bytes, str)):
            raise ValueError("Snapshot content must be bytes or str")
        payload[name] = content.encode("utf-8") if isinstance(content, str) else content
    for name in payload:
        if any(parent.as_posix() in payload for parent in PurePosixPath(name).parents if parent.as_posix() != "."):
            raise ValueError("File/directory key collision")
    # Freeze caller-owned metadata before touching any published state.
    frozen_source = json.loads(json.dumps(source_manifest, allow_nan=False))
    root.mkdir(parents=True, exist_ok=True)
    with _writer_lock(root):
        previous_id = None
        if os.path.lexists(root / "current"):
            previous_id = _open(root).name
        generations = root / "generations"
        if generations.is_symlink():
            raise ValueError("Generations cannot be a symlink")
        generations.mkdir(exist_ok=True)
        snapshot_id = uuid.uuid4().hex
        directory = generations / snapshot_id
        directory.mkdir()
        for name, content in sorted(payload.items()):
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_file(target, content)
        metadata = {
            "version": 1, "snapshot_id": snapshot_id,
            "source_manifest": frozen_source,
            "files": {name: {"sha256": hashlib.sha256(content).hexdigest(),
                             "size": len(content)}
                      for name, content in sorted(payload.items())},
        }
        _write_file(directory / MANIFEST, json.dumps(
            metadata, ensure_ascii=False, sort_keys=True, allow_nan=False
        ).encode("utf-8"))
        for parent, _, _ in os.walk(directory, topdown=False):
            _fsync_directory(parent)
        _fsync_directory(generations)
        _validate_generation(directory, snapshot_id)
        # All failure-prone validation and writes precede this commit point.
        _fsync_directory(root)
        _switch_current(root, snapshot_id)
        try:
            _fsync_directory(root)
        except OSError:
            # A failed durability barrier must not leave a failed publish active.
            if previous_id is None:
                (root / "current").unlink()
            else:
                _switch_current(root, previous_id)
            raise
        return snapshot_id
