"""Verified process-local catalog snapshot for immutable experiment batches.

The caller supplies an already parsed catalog and a fingerprint callback covering
its complete read-only source scope. This cache neither reads nor reparses those
sources and is not a production catalog freshness mechanism.
"""

import copy
import hashlib
from pathlib import Path
from threading import Lock


def catalog_source_fingerprint(workspace_root):
    """Hash all catalog inputs, including membership and disable metadata."""
    root = Path(workspace_root).resolve()
    directory = root / "knowledge" / "products"
    metadata = root / ".doc_meta.json"
    paths = [metadata, directory / "_catalog.yaml"]
    if directory.exists():
        if not directory.resolve().is_relative_to(root):
            raise ValueError("Catalog source leaves its project workspace")
        paths.extend(directory.rglob("*.md"))
    result = {}
    for path in sorted(set(paths)):
        if not path.resolve().is_relative_to(root):
            raise ValueError("Catalog source leaves its project workspace")
        result[path.relative_to(root).as_posix()] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        )
    return result


class VerifiedCatalogCache:
    """Detach one project's catalog; permanently reject a changed source batch.

    ``fingerprint()`` may return nested standard-library values such as a dict
    of source sizes and mtimes. The caller must finish parsing a stable batch
    before construction and keep that source scope read-only during the batch.
    """

    def __init__(self, project_id, catalog, *, fingerprint):
        self.__project_id = copy.deepcopy(project_id)
        self.__catalog = copy.deepcopy(catalog)
        self.__fingerprint = fingerprint
        self.__lock = Lock()
        self.__poisoned = False
        try:
            self.__baseline = copy.deepcopy(fingerprint())
        except Exception as exc:
            raise RuntimeError("Catalog fingerprint failed") from exc

    def load(self, project_id):
        """Return a detached catalog, or fail closed until the cache is rebuilt.

        Wrong-project requests never invoke the callback. Once a matching load
        observes a changed fingerprint or callback failure, even restoring the
        baseline cannot revive this cache; subsequent loads reject immediately.
        """
        if (type(project_id) is not type(self.__project_id)
                or project_id != self.__project_id):
            raise ValueError("Catalog cache project mismatch")
        with self.__lock:
            if self.__poisoned:
                raise RuntimeError("Catalog cache invalidated; rebuild required")
            try:
                current = copy.deepcopy(self.__fingerprint())
                changed = current != self.__baseline
            except Exception as exc:
                self.__poisoned = True
                raise RuntimeError("Catalog fingerprint failed; rebuild required") from exc
            if changed:
                self.__poisoned = True
                raise RuntimeError("Catalog sources changed; rebuild required")
            return copy.deepcopy(self.__catalog)
