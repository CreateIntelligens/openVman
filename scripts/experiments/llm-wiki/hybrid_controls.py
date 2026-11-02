"""Single-factor controls using the actual production LanceDB hybrid search.

The only writable index is an ephemeral container directory outside production
roots. All non-QA vectors, row fields and FTS settings remain unchanged. No
source document, index-state file or serving-process configuration is written.
"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory


ARMS = {
    "main": {},
    "qa_full": {"formal": True, "products": True, "qa_full": True},
    "top_k5": {"formal": True, "products": True, "top_k": 5},
    "context_off": {"formal": True, "products": True, "no_context": True},
}


def row_digest(rows, *, exclude_vector=False):
    content = [{k: v for k, v in row.items() if not exclude_vector or k != "vector"}
               for row in rows]
    content.sort(key=lambda r: (r.get("chunk_id", ""), r.get("path", ""), r.get("text", "")))
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def full_qa_rows(rows, encode, identity):
    """Re-encode only rows tagged with a QA question; never infer a new answer."""
    changed = []
    result = deepcopy(rows)
    for index, row in enumerate(result):
        meta = row.get("metadata", "{}")
        meta = json.loads(meta) if isinstance(meta, str) else meta
        if meta.get("question") and "問題：" in row["text"] and "回答：" in row["text"]:
            changed.append(index)
    for start in range(0, len(changed), 64):
        batch = changed[start:start + 64]
        vectors, spec, _ = encode(
            [result[i]["text"] for i in batch], input_type="document",
            forced_identity=identity,
            titles=[json.loads(result[i]["metadata"]).get("title", "")
                    if isinstance(result[i]["metadata"], str)
                    else result[i]["metadata"].get("title", "") for i in batch],
        )
        if spec.get("identity") != identity or len(vectors) != len(batch):
            raise ValueError("Full-QA embedding identity/count mismatch")
        for index, vector in zip(batch, vectors):
            vector = list(map(float, vector))
            if (len(vector) != len(result[index]["vector"])
                    or not all(math.isfinite(x) for x in vector)
                    or not math.isclose(sum(x*x for x in vector), 1, abs_tol=.01)):
                raise ValueError("Invalid full-QA document vector")
            result[index]["vector"] = vector
    if row_digest(rows, exclude_vector=True) != row_digest(result, exclude_vector=True):
        raise ValueError("Full-QA control changed non-vector fields")
    return result, changed


class ShadowIndex:
    """Own a temporary LanceDB table; selection is patched only in the runner."""

    def __init__(self, table, *, identity, encode):
        import lancedb
        import pyarrow as pa

        self.directory = TemporaryDirectory(prefix="llm-wiki-qa-full-", dir="/tmp")
        self.path = Path(self.directory.name)
        rows = table.to_arrow().to_pylist()
        original_digest = row_digest(rows)
        changed_rows, changed = full_qa_rows(rows, encode, identity)
        connection = lancedb.connect(str(self.path))
        self.table = connection.create_table(
            "qa_full", data=pa.Table.from_pylist(changed_rows, schema=table.schema),
        )
        # Production uses this exact call; reject unexpected index configurations.
        original_indices = table.list_indices()
        if (len(original_indices) != 1 or original_indices[0].index_type != "FTS"
                or list(original_indices[0].columns) != ["text"]):
            raise ValueError("Unexpected production indices; cannot isolate a vector-only factor")
        self.table.create_fts_index("text", replace=True)
        old, new = original_indices[0], self.table.list_indices()[0]
        if old.index_details != new.index_details:
            raise ValueError("Shadow FTS settings differ from production")
        if row_digest(table.to_arrow().to_pylist()) != original_digest:
            raise ValueError("Production index changed during shadow preparation")
        self.audit = {
            "rows": len(rows), "qa_rows_reencoded": len(changed),
            "original_rows_sha256": original_digest,
            "shadow_rows_sha256": row_digest(changed_rows),
            "nonvector_sha256": row_digest(rows, exclude_vector=True),
            "same_nonvector_fields": True, "same_fts_settings": True,
            "fts_settings": old.index_details,
            "production_index_written": False,
        }

    def close(self):
        self.table = None
        self.directory.cleanup()
