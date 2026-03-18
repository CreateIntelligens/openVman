"""Build the knowledge vector index from workspace documents."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from config import get_settings

from infra.db import ensure_fts_index, get_db, get_knowledge_table, normalize_vector, parse_record_metadata
from infra.project_context import resolve_project_context
from knowledge.workspace import ALLOWED_CODE_SUFFIXES, ensure_workspace_scaffold, iter_indexable_documents
from memory.embedder import get_embedder
from personas.personas import extract_persona_id_from_relative_path

_IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_QUESTION_RE = re.compile(r"^Q\s*\d*\s*[：: ]?\s*(.+)$", re.IGNORECASE)
_ANSWER_RE = re.compile(r"^A\s*[：: ]?\s*(.+)$", re.IGNORECASE)


@dataclass(slots=True)
class ChunkSpec:
    text: str
    metadata: dict[str, Any]


def load_index_state(project_id: str = "default") -> dict[str, str]:
    """回傳 { relative_path: fingerprint } 映射。"""
    state = _load_index_state(project_id)
    return state.get("documents", {})


def fingerprint_document(path: Path) -> str:
    """回傳文件的 SHA-256 fingerprint。"""
    return _fingerprint_document(path)


def rebuild_knowledge_index(project_id: str = "default") -> dict[str, Any]:
    """Incrementally rebuild the knowledge table from indexable workspace documents."""
    workspace_root = ensure_workspace_scaffold(project_id)
    documents = iter_indexable_documents(project_id)
    current_fingerprints = {
        path.relative_to(workspace_root).as_posix(): _fingerprint_document(path)
        for path in documents
    }
    state = _load_index_state(project_id)
    existing_records = _load_existing_knowledge_records(project_id)
    reusable_records = _collect_reusable_records(existing_records, current_fingerprints)
    reusable_paths = {
        str(parse_record_metadata(record).get("path", "")).strip()
        for record in reusable_records
    }
    previous_docs = state.get("documents", {})
    changed_paths = [
        path
        for path in documents
        for rel in [path.relative_to(workspace_root).as_posix()]
        if previous_docs.get(rel) != current_fingerprints[rel] or rel not in reusable_paths
    ]
    removed_paths = sorted(set(state.get("documents", {})) - set(current_fingerprints))

    chunk_specs: list[ChunkSpec] = []
    for path in changed_paths:
        if path.suffix.lower() == ".csv":
            chunk_specs.extend(_extract_csv_chunks(path, workspace_root))
            continue
        chunk_specs.extend(_extract_text_chunks(path, workspace_root))

    records = reusable_records + _build_knowledge_records(chunk_specs)
    if not records:
        records = _build_placeholder_records()
    get_db(project_id).create_table("knowledge", data=records, mode="overwrite")
    ensure_fts_index("knowledge", project_id)
    _save_index_state(current_fingerprints, project_id)

    return {
        "status": "ok",
        "workspace_root": str(workspace_root),
        "document_count": len(documents),
        "chunk_count": len(records),
        "changed_documents": len(changed_paths),
        "reused_chunks": len(reusable_records),
        "removed_documents": len(removed_paths),
    }


def _extract_text_chunks(path: Path, workspace_root: Path | None = None) -> list[ChunkSpec]:
    content = path.read_text(encoding="utf-8-sig")
    title = path.stem
    ws = workspace_root or ensure_workspace_scaffold()
    relative_path = path.relative_to(ws).as_posix()
    fingerprint = _fingerprint_document(path)
    persona_id = extract_persona_id_from_relative_path(relative_path)

    # Code files: skip heading parsing, chunk by line groups with overlap
    if path.suffix.lower() in _CODE_EXTENSIONS:
        return _chunk_code_file(content, title, relative_path, fingerprint, persona_id)

    cleaned = _clean_text(content)

    # Strip headings for QA detection (QA docs don't use heading structure)
    stripped = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    qa_chunks = _extract_markdown_qa_chunks(
        stripped,
        title,
        relative_path,
        fingerprint,
        persona_id,
    )
    if qa_chunks:
        return qa_chunks

    return _chunk_by_headings(cleaned, title, relative_path, fingerprint, persona_id)


def _extract_markdown_qa_chunks(
    content: str,
    title: str,
    relative_path: str,
    fingerprint: str,
    persona_id: str,
) -> list[ChunkSpec]:
    chunks: list[ChunkSpec] = []
    question: str | None = None
    answer_lines: list[str] = []
    chunk_index = 0

    def _flush_qa() -> None:
        nonlocal chunk_index
        if question and answer_lines:
            text = _format_qa_chunk(title, question, answer_lines)
            chunks.append(
                ChunkSpec(
                    text=text,
                    metadata={
                        "path": relative_path,
                        "title": title,
                        "heading_path": [],
                        "chunk_index": chunk_index,
                        "kind": "qa_markdown",
                        "question": question,
                        "persona_id": persona_id,
                        "fingerprint": fingerprint,
                        "chunk_id": f"{relative_path}::{chunk_index}",
                        "char_count": len(text),
                    },
                )
            )
            chunk_index += 1

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        question_match = _QUESTION_RE.match(line)
        if question_match:
            _flush_qa()
            question = question_match.group(1).strip()
            answer_lines = []
            continue

        answer_match = _ANSWER_RE.match(line)
        if answer_match:
            answer_lines.append(answer_match.group(1).strip())
            continue

        if question:
            answer_lines.append(line)

    _flush_qa()
    return chunks


_HEADING_LEVEL_RE = re.compile(r"^(#{1,6})\s+(.+)$")

def _chunk_settings() -> tuple[int, int]:
    """Return (char_limit, overlap_chars) from config."""
    cfg = get_settings()
    overlap_chars = int(cfg.chunk_char_limit * cfg.chunk_overlap_ratio)
    return cfg.chunk_char_limit, overlap_chars


_CODE_EXTENSIONS = ALLOWED_CODE_SUFFIXES

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？\n])")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences using Chinese/English punctuation boundaries."""
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [s.strip() for s in parts if s.strip()]


def _semantic_split_sentences(sentences: list[str], threshold: float) -> list[list[str]]:
    """Group sentences into semantic chunks by embedding similarity.

    Adjacent sentences with cosine similarity >= *threshold* stay together.
    When similarity drops below threshold, a new group starts.
    """
    if len(sentences) <= 1:
        return [sentences] if sentences else []

    embedder = get_embedder()
    vectors = embedder.encode(sentences)

    groups: list[list[str]] = [[sentences[0]]]
    for i in range(1, len(sentences)):
        sim = _cosine_similarity(vectors[i - 1], vectors[i])
        if sim >= threshold:
            groups[-1].append(sentences[i])
        else:
            groups.append([sentences[i]])
    return groups


def _semantic_chunk_text(content: str, char_limit: int) -> list[str]:
    """Split content into semantically coherent segments respecting char_limit.

    1. Split into sentences
    2. Group by semantic similarity
    3. Merge small groups / split large groups to stay within char_limit
    """
    cfg = get_settings()
    sentences = _split_into_sentences(content)
    if not sentences:
        return []

    groups = _semantic_split_sentences(sentences, cfg.chunk_semantic_threshold)

    # Merge/split groups to respect char_limit
    segments: list[str] = []
    buffer: list[str] = []
    buffer_len = 0

    for group in groups:
        group_text = "".join(group)
        # If single group exceeds limit, flush buffer first, then add group as-is
        # (it will be further split by _split_oversized_segment later)
        if len(group_text) > char_limit:
            if buffer:
                segments.append("".join(buffer))
                buffer = []
                buffer_len = 0
            segments.append(group_text)
            continue

        if buffer_len + len(group_text) > char_limit:
            segments.append("".join(buffer))
            buffer = list(group)
            buffer_len = len(group_text)
        else:
            buffer.extend(group)
            buffer_len += len(group_text)

    if buffer:
        segments.append("".join(buffer))

    return segments


@dataclass(slots=True, frozen=True)
class _HeadingBlock:
    """A contiguous block of paragraphs under one heading."""

    heading_path: tuple[str, ...]
    paragraphs: tuple[str, ...]


def _parse_heading_blocks(content: str) -> list[_HeadingBlock]:
    """Split markdown into heading-delimited blocks preserving heading hierarchy."""
    heading_stack: list[tuple[int, str]] = []
    blocks: list[_HeadingBlock] = []
    current_paragraphs: list[str] = []

    def _flush() -> None:
        path = tuple(h for _, h in heading_stack)
        text_paragraphs = [p for p in current_paragraphs if p.strip()]
        if text_paragraphs:
            blocks.append(
                _HeadingBlock(
                    heading_path=path,
                    paragraphs=tuple(text_paragraphs),
                )
            )

    for raw_line in content.split("\n"):
        match = _HEADING_LEVEL_RE.match(raw_line.strip())
        if match:
            _flush()
            current_paragraphs = []
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            # Pop headings at same or deeper level
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading_text))
        else:
            current_paragraphs.append(raw_line)

    _flush()
    return blocks


def _extract_python_ast_blocks(content: str) -> list[str]:
    """Extract top-level functions and classes from Python source using AST.

    Returns a list of source code blocks.  If AST parsing fails, returns an
    empty list so the caller can fall back to blank-line splitting.
    """
    import ast
    import textwrap

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    lines = content.splitlines(keepends=True)
    blocks: list[str] = []
    covered: set[int] = set()

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = node.lineno - 1  # 0-indexed
        end = node.end_lineno or (start + 1)
        block = "".join(lines[start:end]).rstrip()
        if block:
            blocks.append(block)
            covered.update(range(start, end))

    # Collect non-covered top-level lines (imports, constants, etc.)
    top_lines: list[str] = []
    for i, line in enumerate(lines):
        if i not in covered:
            top_lines.append(line)

    top_block = "".join(top_lines).strip()
    if top_block:
        blocks.insert(0, top_block)

    return blocks


def _chunk_code_file(
    content: str,
    title: str,
    relative_path: str,
    fingerprint: str,
    persona_id: str,
) -> list[ChunkSpec]:
    """Chunk a code file using AST (Python) or blank-line boundaries (others).

    Python files are split by top-level functions and classes via AST.
    Other code files fall back to blank-line splitting.
    Oversized blocks are further split to stay within char_limit.
    """
    suffix = Path(relative_path).suffix.lower()
    char_limit, overlap_chars = _chunk_settings()

    # Try AST splitting for Python files
    if suffix == ".py":
        ast_blocks = _extract_python_ast_blocks(content)
        if ast_blocks:
            return _assemble_code_chunks(
                ast_blocks, title, relative_path, fingerprint, persona_id, char_limit
            )

    # Fallback: blank-line splitting with overlap
    return _chunk_paragraphs(
        content,
        title,
        relative_path,
        fingerprint,
        persona_id,
        heading_path=(),
        chunk_index_start=0,
        is_code=True,
    )


def _assemble_code_chunks(
    blocks: list[str],
    title: str,
    relative_path: str,
    fingerprint: str,
    persona_id: str,
    char_limit: int,
) -> list[ChunkSpec]:
    """Assemble AST blocks into ChunkSpecs, merging small blocks and splitting large ones."""
    chunks: list[ChunkSpec] = []
    buffer: list[str] = []
    buffer_len = 0
    chunk_index = 0

    def _flush() -> None:
        nonlocal chunk_index
        if not buffer:
            return
        chunk_text = "\n\n".join(buffer)
        full_text = f"檔案：{relative_path}\n{chunk_text}"
        chunks.append(
            ChunkSpec(
                text=full_text,
                metadata={
                    "path": relative_path,
                    "title": title,
                    "heading_path": [],
                    "chunk_index": chunk_index,
                    "kind": "code",
                    "persona_id": persona_id,
                    "fingerprint": fingerprint,
                    "chunk_id": f"{relative_path}::{chunk_index}",
                    "char_count": len(full_text),
                },
            )
        )
        chunk_index += 1

    for block in blocks:
        # If a single block exceeds limit, flush buffer first, then split the block
        if len(block) > char_limit:
            _flush()
            buffer = []
            buffer_len = 0
            sub_pieces = _split_oversized_segment(block, char_limit)
            for piece in sub_pieces:
                buffer = [piece]
                buffer_len = len(piece)
                _flush()
                buffer = []
                buffer_len = 0
            continue

        if buffer and buffer_len + len(block) + 2 > char_limit:
            _flush()
            buffer = [block]
            buffer_len = len(block)
        else:
            buffer.append(block)
            buffer_len += len(block) + (2 if len(buffer) > 1 else 0)

    _flush()
    return chunks


def _chunk_by_headings(
    content: str,
    title: str,
    relative_path: str,
    fingerprint: str,
    persona_id: str,
) -> list[ChunkSpec]:
    blocks = _parse_heading_blocks(content)
    if not blocks:
        # No headings found — fall back to plain paragraph splitting
        return _chunk_paragraphs(
            content, title, relative_path, fingerprint, persona_id, heading_path=()
        )

    chunks: list[ChunkSpec] = []
    for block in blocks:
        block_chunks = _chunk_paragraphs(
            "\n\n".join(block.paragraphs),
            title,
            relative_path,
            fingerprint,
            persona_id,
            heading_path=block.heading_path,
            chunk_index_start=len(chunks),
        )
        chunks.extend(block_chunks)
    return chunks


def _split_oversized_segment(segment: str, char_limit: int) -> list[str]:
    """Split a single segment that exceeds char_limit into smaller pieces.

    Tries to split on sentence boundaries (。！？\n) first, falls back to
    hard character splits at *char_limit* intervals.
    """
    if len(segment) <= char_limit:
        return [segment]

    pieces: list[str] = []
    sentence_re = re.compile(r"(?<=[。！？\n])")
    sentences = [s for s in sentence_re.split(segment) if s.strip()]

    buf: list[str] = []
    buf_len = 0
    for sentence in sentences:
        if buf and buf_len + len(sentence) > char_limit:
            pieces.append("".join(buf))
            buf = [sentence]
            buf_len = len(sentence)
        else:
            buf.append(sentence)
            buf_len += len(sentence)
    if buf:
        pieces.append("".join(buf))

    # If sentence splitting still left oversized pieces, hard-split them
    final: list[str] = []
    for piece in pieces:
        while len(piece) > char_limit:
            final.append(piece[:char_limit])
            piece = piece[char_limit:]
        if piece.strip():
            final.append(piece)
    return final


def _chunk_paragraphs(
    content: str,
    title: str,
    relative_path: str,
    fingerprint: str,
    persona_id: str,
    *,
    heading_path: tuple[str, ...] = (),
    chunk_index_start: int = 0,
    is_code: bool = False,
) -> list[ChunkSpec]:
    char_limit, overlap_chars = _chunk_settings()
    kind = "code" if is_code else "freeform_markdown"

    if is_code:
        # Code files: split by blank lines (natural function/class boundaries)
        raw_segments = [s.strip() for s in content.split("\n\n") if s.strip()]
        segments: list[str] = []
        for seg in raw_segments:
            segments.extend(_split_oversized_segment(seg, char_limit))
    else:
        # Markdown/text: use semantic chunking for coherent segments
        segments = _semantic_chunk_text(content, char_limit)
        # Further split any oversized semantic segments
        final_segments: list[str] = []
        for seg in segments:
            final_segments.extend(_split_oversized_segment(seg, char_limit))
        segments = final_segments

    if not segments:
        return []

    chunks: list[ChunkSpec] = []
    buffer: list[str] = []
    current_length = 0
    chunk_index = chunk_index_start

    heading_label = " > ".join(heading_path) if heading_path else ""

    def _make_chunk(chunk_text: str) -> ChunkSpec:
        if is_code:
            full_text = f"檔案：{relative_path}\n{chunk_text}"
        else:
            prefix = f"主題：{title}"
            if heading_label:
                prefix += f"\n章節：{heading_label}"
            full_text = f"{prefix}\n內容：{chunk_text}"
        return ChunkSpec(
            text=full_text,
            metadata={
                "path": relative_path,
                "title": title,
                "heading_path": list(heading_path),
                "chunk_index": chunk_index,
                "kind": kind,
                "persona_id": persona_id,
                "fingerprint": fingerprint,
                "chunk_id": f"{relative_path}::{chunk_index}",
                "char_count": len(full_text),
            },
        )

    def _flush_buffer() -> list[str]:
        """Flush buffer into a chunk and return overlap segments for next chunk."""
        nonlocal chunk_index
        if not buffer:
            return []
        chunk_text = "\n\n".join(buffer)
        chunks.append(_make_chunk(chunk_text))
        chunk_index += 1

        if overlap_chars <= 0:
            return []

        # Collect trailing segments that fit within overlap_chars.
        # Always include at least the last segment for continuity.
        overlap_segs: list[str] = []
        overlap_len = 0
        for seg in reversed(buffer):
            candidate = len(seg) + (2 if overlap_segs else 0)
            if overlap_segs and overlap_len + candidate > overlap_chars:
                break
            overlap_segs.insert(0, seg)
            overlap_len += candidate
        return overlap_segs

    for segment in segments:
        additional = len(segment) + (2 if buffer else 0)
        if buffer and current_length + additional > char_limit:
            overlap_segs = _flush_buffer()
            buffer = overlap_segs + [segment]
            current_length = sum(len(s) for s in buffer) + 2 * max(len(buffer) - 1, 0)
            continue

        buffer.append(segment)
        current_length += additional

    _flush_buffer()
    return chunks


def _extract_csv_chunks(path: Path, workspace_root: Path | None = None) -> list[ChunkSpec]:
    chunks: list[ChunkSpec] = []
    ws = workspace_root or ensure_workspace_scaffold()
    relative_path = path.relative_to(ws).as_posix()
    title = path.stem
    fingerprint = _fingerprint_document(path)
    persona_id = extract_persona_id_from_relative_path(relative_path)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            question = _pick_first(row, "q", "question", "Q", "題目")
            answer = _pick_first(row, "a", "answer", "A", "答案")
            if not question and not answer:
                continue

            text = _format_qa_chunk(title, question or "未命名問題", [answer or ""])
            chunks.append(
                ChunkSpec(
                    text=text,
                    metadata={
                        "path": relative_path,
                        "title": title,
                        "heading_path": [],
                        "chunk_index": row_number,
                        "kind": "qa_csv",
                        "question": question,
                        "persona_id": persona_id,
                        "row_number": row_number,
                        "row_index": _pick_first(row, "index", "id"),
                        "image": _pick_first(row, "img", "image"),
                        "fingerprint": fingerprint,
                        "chunk_id": f"{relative_path}::{row_number}",
                        "char_count": len(text),
                    },
                )
            )

    return chunks


def _build_knowledge_records(chunk_specs: list[ChunkSpec]) -> list[dict[str, Any]]:
    if not chunk_specs:
        return []

    texts = [chunk.text for chunk in chunk_specs]
    vectors = get_embedder().encode(texts)
    records: list[dict[str, Any]] = []

    for chunk, vector in zip(chunk_specs, vectors):
        records.append(
            {
                "text": chunk.text,
                "vector": normalize_vector(vector),
                "source": "workspace",
                "date": date.today().isoformat(),
                "metadata": json.dumps(chunk.metadata, ensure_ascii=False),
            }
        )

    return records


def _build_placeholder_records() -> list[dict[str, Any]]:
    return [
        {
            "text": "知識庫目前沒有內容。",
            "vector": normalize_vector(get_embedder().encode(["知識庫目前沒有內容。"])[0]),
            "source": "system",
            "date": date.today().isoformat(),
            "metadata": json.dumps({"placeholder": True}, ensure_ascii=False),
        }
    ]


def _clean_text(content: str) -> str:
    """Remove image markdown but preserve headings for heading-aware chunking."""
    return "\n".join(
        _IMAGE_MARKDOWN_RE.sub("", line) for line in content.splitlines()
    ).strip()


def _format_qa_chunk(title: str, question: str, answer_lines: list[str]) -> str:
    answer = "\n".join(line.strip() for line in answer_lines if line.strip())
    return f"主題：{title}\n問題：{question.strip()}\n回答：{answer}"


def _pick_first(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _fingerprint_document(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_existing_knowledge_records(project_id: str = "default") -> list[dict[str, Any]]:
    db = get_db(project_id)
    if "knowledge" not in db.table_names():
        return []
    return get_knowledge_table(project_id).to_arrow().to_pylist()


def _collect_reusable_records(
    records: list[dict[str, Any]],
    current_fingerprints: dict[str, str],
) -> list[dict[str, Any]]:
    reusable: list[dict[str, Any]] = []
    for record in records:
        metadata = parse_record_metadata(record)
        if metadata.get("placeholder"):
            continue
        path = str(metadata.get("path", "")).strip()
        fingerprint = str(metadata.get("fingerprint", "")).strip()
        if not path or not fingerprint:
            continue
        if current_fingerprints.get(path) != fingerprint:
            continue
        reusable.append(record)
    return reusable


def _load_index_state(project_id: str = "default") -> dict[str, Any]:
    ctx = resolve_project_context(project_id)
    path = ctx.index_state_path
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _save_index_state(documents: dict[str, str], project_id: str = "default") -> None:
    ctx = resolve_project_context(project_id)
    path = ctx.index_state_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "updated_at": date.today().isoformat(),
                "documents": documents,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
