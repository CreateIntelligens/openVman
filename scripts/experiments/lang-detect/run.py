"""比較三種語言判斷：規則、Jev、主對話 LLM。

在 api 容器內執行（要 TYPESAFE_API_KEY 與 LLM key）：
    docker cp scripts/experiments/lang-detect/run.py openvman-api-1:/tmp/lang_run.py
    docker exec -w /app openvman-api-1 python /tmp/lang_run.py
只分 zh／en／es；其他語言與判斷不出來的算 zh。
"""

from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "/app")

from core.jev_client import jev_nouls  # noqa: E402
from core.llm_client import generate_chat_reply  # noqa: E402
from memory.language_detect import detect_language  # noqa: E402

CASES: list[tuple[str, str]] = [
    # 中文（含夾英文型號、繁簡、注音輸入殘留）
    ("你好，地下室要抽污水，你推薦哪一款泵浦？", "zh"),
    ("EUS 系列 2HP 的揚程多少？", "zh"),
    ("50EUBL 跟 HIPPO 差在哪", "zh"),
    ("请问这个泵浦多少钱", "zh"),
    ("好", "zh"),
    ("謝謝", "zh"),
    ("我要 OK 的那款", "zh"),
    ("DIVA PRO 有 agitator 嗎", "zh"),
    ("可以用 LINE 聯絡業務嗎", "zh"),
    ("嗯嗯", "zh"),
    # 英文
    ("Hi, which pump would you recommend for draining dirty water?", "en"),
    ("What is the max head of the EUS series?", "en"),
    ("thanks", "en"),
    ("ok", "en"),
    ("Can I talk to a sales engineer?", "en"),
    ("How much is it", "en"),
    ("Do you ship to Mexico?", "en"),
    ("hello", "en"),
    ("I need a pump for my basement", "en"),
    ("Is the DIVA PRO suitable for sludge", "en"),
    # 西語（含無重音、無 ¿）
    ("Hola, ¿qué bomba me recomiendas para sacar agua sucia?", "es"),
    ("quiero una bomba para el sotano", "es"),
    ("gracias", "es"),
    ("hola", "es"),
    ("cuanto cuesta", "es"),
    ("Necesito hablar con un ingeniero de ventas", "es"),
    ("La bomba EUS sirve para agua con lodo?", "es"),
    ("buenos dias", "es"),
    ("me pueden enviar el catalogo", "es"),
    ("Tienen distribuidores en Mexico", "es"),
    # 其他語言與雜訊 → zh
    ("ポンプを探しています", "zh"),
    ("펌프 추천해 주세요", "zh"),
    ("Guten Tag", "zh"),
    ("12345", "zh"),
    ("...", "zh"),
    ("EUS", "zh"),
]

JEV_QUESTIONS = {
    "en": {
        "instructions": "這句使用者訊息主要是用英文寫的嗎？",
        "criteria": {"true": "主要語言是英文", "false": "主要語言是中文、西班牙文或其他語言，或只有型號數字"},
    },
    "es": {
        "instructions": "這句使用者訊息主要是用西班牙文寫的嗎？",
        "criteria": {"true": "主要語言是西班牙文", "false": "主要語言是中文、英文或其他語言，或只有型號數字"},
    },
}

LLM_PROMPT = (
    "判斷下面這句使用者訊息的主要語言。只回一個代碼：zh、en 或 es。"
    "中文（含夾英文型號）回 zh；其他語言或判斷不出來也回 zh。\n\n訊息：{text}"
)


def by_jev(text: str) -> str:
    scores = jev_nouls(text, JEV_QUESTIONS, timeout=10)
    best = max(scores, key=scores.get)
    return best if scores[best] >= 0.5 else "zh"


def by_llm(text: str) -> str:
    reply = generate_chat_reply(
        [{"role": "user", "content": LLM_PROMPT.format(text=text)}],
        trace_id="lang-detect-exp",
    ).strip().lower()
    return reply if reply in {"zh", "en", "es"} else "zh"


def main() -> None:
    methods = {"rules": detect_language, "jev": by_jev, "llm": by_llm}
    summary: dict[str, dict] = {}
    rows = []
    for name, fn in methods.items():
        correct, latencies, misses = 0, [], []
        for text, expected in CASES:
            start = time.perf_counter()
            try:
                got = fn(text)
            except Exception as exc:  # noqa: BLE001
                got = f"ERR:{type(exc).__name__}"
            latencies.append((time.perf_counter() - start) * 1000)
            if got == expected:
                correct += 1
            else:
                misses.append((text, expected, got))
            rows.append({"method": name, "text": text, "expected": expected, "got": got})
        latencies.sort()
        summary[name] = {
            "correct": f"{correct}/{len(CASES)}",
            "p50_ms": round(latencies[len(latencies) // 2], 1),
            "p95_ms": round(latencies[int(len(latencies) * 0.95) - 1], 1),
            "misses": misses,
        }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    with open("/tmp/lang_result.json", "w") as fh:
        json.dump({"summary": summary, "rows": rows}, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
