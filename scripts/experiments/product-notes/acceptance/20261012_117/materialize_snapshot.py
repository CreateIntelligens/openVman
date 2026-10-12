"""Recreate local views from the immutable source snapshot, without providers."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile

ROOT = Path(__file__).resolve().parent


def materialize(root=ROOT):
    snapshot = json.loads((root / "source_snapshot.json").read_text())
    files, hashes = snapshot["files"], snapshot["hashes"]
    if set(files) != set(hashes):
        raise ValueError("Snapshot file/hash sets differ")
    exports = {}
    for name, value in files.items():
        if hashlib.sha256(value.encode()).hexdigest() != hashes[name]:
            raise ValueError(f"Snapshot content hash mismatch: {name}")
        if name.startswith("knowledge/products/") and name.endswith(".md"):
            relative = PurePosixPath(name).relative_to("knowledge/products")
            if len(relative.parts) != 1 or relative.name in (".", ".."):
                raise ValueError("Unsafe snapshot note path")
            exports[root / "notes" / relative.name] = value
    for source, target in (
        ("knowledge/EVAK_CATALOG.md", "source_catalog.md"),
        ("knowledge/products/_catalog.yaml", "catalog.yaml"),
    ):
        exports[root / target] = files[source]
    # Preflight every existing file before writing any missing views.
    for path, value in exports.items():
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("Symlink export path is not allowed")
        if path.exists() and path.read_bytes() != value.encode():
            raise ValueError(f"Existing export differs; not overwriting: {path.name}")
    created = 0
    for path, value in exports.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(value.encode())
            created += 1
    return {"status": "verified", "exports": len(exports), "created": created}


def self_test():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        files = {
            "knowledge/products/P-1.md": "---\nmodel: P-1\n---\n",
            "knowledge/products/_catalog.yaml": "name: sample\n",
            "knowledge/EVAK_CATALOG.md": "原文\n",
        }
        snapshot = {"files": files, "hashes": {
            name: hashlib.sha256(value.encode()).hexdigest()
            for name, value in files.items()
        }}
        source = root / "source_snapshot.json"
        source.write_text(json.dumps(snapshot, ensure_ascii=False))
        assert materialize(root)["created"] == 3
        assert materialize(root)["created"] == 0
        (root / "notes/P-1.md").write_text("local edit")
        (root / "catalog.yaml").unlink()
        try:
            materialize(root)
        except ValueError:
            pass
        else:
            raise AssertionError("Edited view must be rejected")
        assert not (root / "catalog.yaml").exists()
        assert (root / "notes/P-1.md").read_text() == "local edit"
        snapshot["files"]["knowledge/products/P-1.md"] = "tampered"
        source.write_text(json.dumps(snapshot))
        try:
            materialize(root)
        except ValueError:
            pass
        else:
            raise AssertionError("Snapshot hash mismatch must fail")
    print("Snapshot restore fixtures passed; no provider or live data access")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    self_test() if args.self_test else print(json.dumps(materialize()))
