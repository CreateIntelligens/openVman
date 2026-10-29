"""Conservative structural QA checks; findings require manual review."""

import argparse
import json
from pathlib import Path
import re
import unicodedata

from experiment_io import validate_output


GENERIC_QUESTIONS = (
    r"(?:如何|怎麼|怎樣)(?:預防|治療|診斷|預約|掛號|檢查|照護|照顧)",
    r"(?:有什麼|有哪些|常見的?|主要的?)?"
    r"(?:症狀|原因|併發症|後遺症|危險因子|注意事項)"
    r"(?:有什麼|有哪些|是什麼)?",
    r"(?:預約|掛號|檢查|治療)?(?:費用|價格)"
    r"(?:多少|是多少|怎麼算|如何計算)?",
    r"(?:預約|掛號)(?:方式|流程|方法)",
    r"(?:如何|怎麼|怎樣)(?:預約|掛號)(?:方式|流程|方法)",
    r"(?:需要|要)(?:注意什麼|注意哪些事項)",
    r"(?:howtoprevent|whatarethesymptoms|howtobook|howmuchdoesitcost)",
)
GENERIC_RE = re.compile("(?:" + "|".join(GENERIC_QUESTIONS) + ")")
PREFIX_RE = re.compile(r"^(?:請問一下|想請問|請問|想知道)")
URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
INVISIBLE_RE = re.compile(r"[\s\u200b\u200c\u200d\ufeff]+")
QUESTION_PUNCTUATION_RE = re.compile(r"[?？。.!！]+$")

# A closed grammar deliberately leaves uncertain or operational answers alone.
# In particular, 看診/掛號/預約 are not permitted as a redirection suffix.
REDIRECT_RE = re.compile(
    r"(?:請|可|可以|建議|您可|您可以|民眾可)?"
    r"(?:"
    r"(?:掃描|掃瞄|掃|參考|詳見)(?:以下|下方|上方|圖中|此)?的?"
    r"qr(?:code|碼)?"
    r"|(?:加入|加)(?:我們的|官方|本院|醫院)?line(?:官方帳號|帳號)?"
    r"|(?:至|到|前往|查看|參考|瀏覽|點選|點擊|詳見|詳洽)"
    r"(?:本院|醫院|我們的|以下|下方|相關)?(?:官網|官方網站)"
    r")"
    r"(?:以|來|即可|可|進行)?"
    r"(?:查看|查詢|了解|瞭解|參閱|洽詢|諮詢|詢問|看)?"
    r"(?:詳情|詳細資訊|詳細說明|更多資訊|相關資訊|相關說明|資訊|內容|說明)?"
)
ANSWER_PUNCTUATION_RE = re.compile(r"[，,。.!！?？:：;；()（）\[\]【】]+")


def compact(value):
    """Normalize typography without adding medical or operational knowledge."""
    text = unicodedata.normalize("NFKC", value or "")
    return INVISIBLE_RE.sub("", text).casefold()


def generic_question(question):
    normalized = QUESTION_PUNCTUATION_RE.sub("", compact(question))
    normalized = PREFIX_RE.sub("", normalized)
    # Full matching prevents a named disease or service from being discarded.
    return GENERIC_RE.fullmatch(normalized) is not None


def redirect_only(answer):
    without_urls = URL_RE.sub("", answer)
    normalized = ANSWER_PUNCTUATION_RE.sub("", compact(without_urls))
    return REDIRECT_RE.fullmatch(normalized) is not None


def lint_rows(rows):
    """Return review candidates without editing rows or inferring facts."""
    findings = []
    for row in rows:
        row_id = f"{row['file']}#{row['index']}"
        question = row.get("q") or ""
        answer = row.get("a") or ""
        if generic_question(question):
            findings.append({
                "type": "ambiguous_question",
                "id": row_id,
                "evidence": question,
                "reason": (
                    "問題完整符合泛稱問句白名單，未明列疾病或服務主詞；"
                    "需人工確認是否依賴檔案主題或前文。"
                ),
            })
        if not compact(answer):
            findings.append({
                "type": "empty_answer",
                "id": row_id,
                "evidence": "答案為空白（忽略空白及不可見分隔字元）。",
                "reason": "答案沒有文字，需人工確認並補充內容。",
            })
        elif redirect_only(answer):
            # URLs can contain personal identifiers; the matched grammar itself
            # contains only generic channel words, so retain that evidence.
            evidence = URL_RE.sub("", answer).strip()
            findings.append({
                "type": "redirect_only",
                "id": row_id,
                "evidence": evidence,
                "reason": (
                    "答案完整符合掃碼、加入 LINE 或前往官網的純導向語法；"
                    "未含具體業務資訊，需人工確認是否補充實質答案。"
                ),
            })
    counts = {}
    for finding in findings:
        kind = finding["type"]
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "mode": "manual_review_only",
        "summary": {
            "rows": len(rows),
            "findings": len(findings),
            "by_type": counts,
        },
        "findings": findings,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.rows.resolve() == args.output.resolve():
        parser.error("--output must differ from --rows")
    try:
        args.output = validate_output(args.output, inputs=[args.rows])
    except ValueError as exc:
        parser.error(str(exc))
    rows = json.loads(args.rows.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) and "file" in row and "index" in row
        for row in rows
    ):
        parser.error("--rows must contain a list with file/index identifiers")
    report = lint_rows(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
