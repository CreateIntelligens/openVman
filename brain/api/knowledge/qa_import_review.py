"""Per-question languages and plain-language notes for an imported QA table.

客戶給的表常常中英西混在一起、欄名五花八門。這裡負責兩件事：表裡混了不同語言時逐題標上語言，
以及把匯入時系統替使用者做的決定、略過的東西寫成白話提示，讓工作人員知道要回頭補什麼。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from knowledge.converters import qa_table_ignored_columns
from knowledge.qa_csv import (
    label_qa_csv_languages,
    normalize_row_language,
    parse_qa_csv,
    qa_csv_row_extras,
)

# 提示裡的語言名稱，用工作人員看得懂的寫法；分類名稱則照 qa_nodes.LANGUAGE_LABELS。
LANGUAGE_NAMES: dict[str, str] = {
    "zh": "中文",
    "en": "English",
    "es": "Español",
    "ja": "日本語",
    "ko": "한국어",
    "nan": "台語",
}

_LIST_LIMIT = 3


def _short(text: str, limit: int = 20) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else f"{flat[:limit]}…"


def _listing(items: list[str], limit: int | None = _LIST_LIMIT) -> str:
    """Name the questions; ``limit=None`` names every one (a refusal must, or the fix takes several uploads)."""
    shown = "、".join(f"「{_short(item)}」" for item in items[:limit])
    return f"{shown}等 {len(items)} 題" if limit is not None and len(items) > limit else shown


def label_mixed_languages(qa_csv: bytes, *, force: bool = False) -> bytes:
    """Write each question's language into the table when it mixes languages.

    整份只有一種語言、也沒人標語言時不動，照舊整份一個語言、存成 Markdown。混了語言才逐題判斷，
    否則英文題會跟著整份放進「中文」分類，搜尋也排錯。人寫的語言不改，看不懂的值也留著，只補空白。
    ``force``：同名文件已經依語言分開時，這次只有一種語言也要標，新題才放得進對的語言分類。
    """
    from memory.language_detect import detect_document_language, detect_row_language

    entries = parse_qa_csv(qa_csv)
    if not entries:
        return qa_csv
    texts = [f"{entry['q']} {entry['a']}" for entry in entries]
    fallback = detect_document_language(" ".join(texts)[:4000])
    labels = [row["language"] for row in qa_csv_row_extras(qa_csv).values()]
    if all(labels):
        # 全部都標了就不重寫：重寫會把格子裡的 \r\n 統一成 \n，重傳時題目對不上舊檔，多出一份。
        return qa_csv
    if not force and not any(labels) and len({detect_row_language(text, fallback) for text in texts}) < 2:
        return qa_csv
    try:
        content, _ = label_qa_csv_languages(
            qa_csv, lambda text: detect_row_language(text, fallback),
        )
    except ValueError:
        return qa_csv
    return content.encode("utf-8")


def stored_split(filename: str, project_id: str) -> bool:
    """Whether the stored QA table of the same name already splits its questions by language."""
    from knowledge.qa_nodes import is_qa_document
    from knowledge.workspace import ensure_workspace_scaffold

    relative = (Path("knowledge/qa") / filename).with_suffix(".csv")
    path = ensure_workspace_scaffold(project_id) / relative
    if not path.is_file() or not is_qa_document(relative.as_posix(), project_id):
        return False
    return is_mixed(row_languages(qa_csv_row_extras(path.read_bytes())))


SINGLE_LANGUAGE_FILE_NOTE = (
    "這份表原本只有一種語言，這次多了其他語言的題目，先跟原本的題目放在一起。"
    "要依語言分開放，請把檔名改掉重新上傳，或在快速問答把題目拖到對的分類"
)


@dataclass
class QaTable:
    """An uploaded QA table after languages were labelled, ready to store and place."""

    qa_csv: bytes
    extras: dict[str, dict[str, Any]]
    languages: dict[str, str]
    already_split: bool
    ignored: list[str] = field(default_factory=list)

    def split_for(self, target: Path, project_id: str, notes: list[str]) -> bool:
        """Whether to place each question under its own language for this target.

        原本是 Markdown 的同名文件存不了每題的語言，分開放了搜尋也排不對，照舊放在一起並說明。
        """
        from knowledge.qa_nodes import is_qa_document

        mixed = is_mixed(self.languages) or self.already_split
        if mixed and target.suffix == ".md" and is_qa_document(target.as_posix(), project_id):
            notes.append(SINGLE_LANGUAGE_FILE_NOTE)
            return False
        return mixed


def prepare_qa_table(source: Path, origin_bytes: bytes, qa_csv: bytes, project_id: str) -> QaTable:
    """Label languages and read what the import will skip, before the original is archived."""
    already_split = stored_split(source.name, project_id)
    labelled = label_mixed_languages(qa_csv, force=already_split)
    extras = qa_csv_row_extras(labelled)
    return QaTable(
        qa_csv=labelled,
        extras=extras,
        languages=row_languages(extras),
        already_split=already_split,
        ignored=qa_table_ignored_columns(source, origin_bytes),
    )


def row_languages(extras: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Each question's language code, for rows whose label this code understands."""
    return {
        question: code
        for question, row in extras.items()
        if (code := normalize_row_language(row["language"]))
    }


def is_mixed(languages: dict[str, str]) -> bool:
    return len(set(languages.values())) > 1


def question_paths(
    extras: dict[str, dict[str, Any]],
    languages: dict[str, str],
    file_category: str | None,
    stem: str,
    project_id: str,
    *,
    report_missing: bool,
) -> tuple[dict[str, list[str]], dict[str, int], bool]:
    """Where each question goes, languages with no category yet, and whether any went by language.

    有填 path 的照填的放。沒填的放進以檔名命名的分類，上層是語言分類：``languages`` 有值（混語言的表）
    時用每題自己的語言，否則用整份的分類。語言分類不自動建立，沒有就放最上層；專案有其他語言分類時，
    缺的那些回報給使用者。
    """
    from knowledge.qa_nodes import LANGUAGE_LABELS, find_language_category, node_label

    # 台語沒有對應的分類名稱，提示「先建分類」也沒用，只報建得出來的語言。
    nameable = set(LANGUAGE_LABELS.values())
    categories = {code: find_language_category(code, project_id) for code in set(languages.values())}
    has_language_categories = file_category is not None or any(categories.values())
    missing: Counter[str] = Counter()
    paths: dict[str, list[str]] = {}
    by_language = False
    for question, row in extras.items():
        if row["path"]:
            paths[question] = row["path"]
            continue
        code = languages.get(question)
        chosen = categories[code] if code else file_category
        if code in nameable and chosen is None and has_language_categories and report_missing:
            missing[code] += 1
        by_language = by_language or bool(code and chosen)
        paths[question] = [*([node_label(chosen, project_id)] if chosen else []), stem]
    return paths, dict(missing), by_language


def missing_language_category(language: str, category: str | None, project_id: str) -> dict[str, int]:
    """The file's language when the project sorts by language but lacks that category."""
    from knowledge.qa_nodes import LANGUAGE_LABELS, find_language_category

    if category is not None or language not in set(LANGUAGE_LABELS.values()) or not any(
        find_language_category(code, project_id) for code in set(LANGUAGE_LABELS.values())
    ):
        return {}
    return {language: 0}


def unclear_question_problems(entries: list[dict[str, Any]], untitled: str) -> list[str]:
    """Every row the quick Q&A cannot show correctly, so one upload lists them all.

    編輯器一題只顯示一個答案，同一題有兩個答案時另一個會看不到，AI 卻兩個都查得到；
    沒有題目的列在選單上只會是一顆「未命名問題」。
    """
    orphans: list[str] = []
    answers: dict[str, str] = {}
    conflicts: list[str] = []
    for entry in entries:
        question, answer = entry["q"].strip(), entry["a"].strip()
        if question == untitled:
            orphans.append(answer)
        elif answers.setdefault(question, answer) != answer and question not in conflicts:
            conflicts.append(question)
    problems: list[str] = []
    if orphans:
        problems.append(f"{len(orphans)} 列只有答案、沒有題目（{_listing(orphans, None)}），請補上題目")
    if conflicts:
        problems.append(f"{_listing(conflicts, None)}在檔案裡有不同的答案，每題請只留一個答案")
    return problems


def qa_table_notes(
    *,
    ignored: list[str],
    entries: list[dict[str, Any]],
    extras: dict[str, dict[str, Any]],
    missing_categories: dict[str, int],
    stem: str,
    image_exists: Any,
) -> list[str]:
    """What a person should know about an imported QA table, in plain words."""
    notes: list[str] = []
    if ignored:
        notes.append(f"這些欄位沒有讀進去：{'、'.join(ignored)}")
    unknown = Counter(
        row["language"].strip()
        for row in extras.values()
        if row["language"].strip() and not normalize_row_language(row["language"])
    )
    if unknown:
        values = "、".join(f"「{value}」{count} 題" for value, count in unknown.items())
        notes.append(f"語言欄看不懂：{values}，這幾題照整份的語言處理。語言請填中文、英文、西文、日文或韓文")
    for code, count in missing_categories.items():
        name = LANGUAGE_NAMES.get(code, code)
        which = f"{name} 的 {count} 題" if count else "這份"
        notes.append(
            f"還沒有「{name}」分類，{which}先放在最上層的「{stem}」。"
            f"要放進語言分類，請先建立「{name}」分類再把它拖進去"
        )
    unanswered = [entry["q"] for entry in entries if entry["q"].strip() and not entry["a"].strip()]
    if unanswered:
        notes.append(f"{_listing(unanswered)}沒有答案，請到快速問答補上")
    missing_images = [entry["img"] for entry in entries if entry["img"] and not image_exists(entry["img"])]
    if missing_images:
        shown = "、".join(dict.fromkeys(missing_images[:_LIST_LIMIT]))
        notes.append(f"{len(missing_images)} 題的圖片找不到（{shown}），請到快速問答的題目裡加圖")
    return notes


def not_a_qa_table_note(source: Path) -> str | None:
    """Why a spreadsheet became an ordinary document, when it may have been meant as Q&A."""
    suffix = source.suffix.lower()
    if suffix == ".csv":
        return "這份表格沒有「問題」「答案」兩欄，所以當成一般文件匯入。要放進快速問答，欄名請用「問題」「答案」"
    if suffix == ".xlsx":
        return (
            "這份 Excel 不是每張工作表都有「問題」「答案」兩欄，所以整本當成一般文件匯入。"
            "要放進快速問答，每張有資料的工作表都要有這兩欄"
        )
    return None


def language_counts(languages: dict[str, str]) -> dict[str, int]:
    return dict(Counter(languages.values()))
