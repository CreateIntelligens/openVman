"""Jev 能不能在串流辨識的「最後暫定字幕」與「定稿」之間挑對（在 api 容器內執行）。

不重送音訊，只看文字與情境。每組正反順序各問一次，檢查順序穩定性。
結果寫到 /tmp/asr_judge.json。
"""
import json
import sys
import time

sys.path.insert(0, "/app")
from core.jev_client import jev_nouls

HEKEE = "專案：EVAK 泵浦產品與水機工程技術諮詢。這個專案的使用者可能說：繁體中文、英文、西班牙文。"
PREV = "虛擬人上一句：您好，我是小鶴，請問想了解哪一款泵浦？"
# (interim, final, 正解：interim / final / either)
CASES = [
    ("who am i", "OMI", "interim"),
    ("你是誰", "你是水", "interim"),
    ("EUBL 的馬力多少", "一步的馬力多少", "interim"),
    ("hola, ¿cómo estás?", "올라 코모 에스타스", "interim"),
    ("What is the flow rate of HIPPO", "What is the floor rate of hippo", "interim"),
    ("請問 DIVA 有攪拌器嗎", "請問低瓦有攪拌器嗎", "interim"),
    ("Can you speak English", "肯你死逼英格利許", "interim"),
    ("我想問沉水泵", "我想問陳水扁", "interim"),
    ("水溫限制是幾度", "수온 제한은 몇 도", "interim"),
    ("O and I", "who am i", "final"),
    ("who am", "Who am I?", "final"),
    ("污泥 泵 有 幾 馬", "污泥泵有幾匹馬力？", "final"),
    ("What's the the max head of", "What's the max head of the DIVA pump?", "final"),
    ("¿Qué modelo tiene agi", "¿Qué modelo tiene agitador?", "final"),
    ("你們電話幾號 嗯 嗯", "你們電話幾號？", "final"),
    ("我要找 50 E U B L", "我要找 50EUBL", "final"),
    ("안녕하세요 펌프", "你好，泵浦", "final"),
    ("eubl horse power", "EUBL horsepower?", "either"),
    ("¿Cuánto cuesta la bomba?", "Cuanto cuesta la bomba", "either"),
    ("ok thanks bye", "OK, thanks, bye.", "either"),
]


def plausible(text: str) -> dict:
    # 各自單獨問，不讓兩個版本互相比：比較式問法會偏向排在前面的那個（v1 實測 2/20 翻轉）。
    return {
        "instructions": f"語音辨識把使用者的話轉成「{text}」，這像是正確辨識出來的一句話嗎？",
        "criteria": {
            # v2 要求「符合專案情境」，把正常閒聊（who am i）也打成 0.08；情境只拿來分辨同音字。
            "true": "通順、像真人會說的話，是上述語言之一；跟專案無關的閒聊或測試也算。專有名詞（型號、品牌）拼對",
            "false": "有聽錯的同音字（例如把型號聽成別的詞）、無意義的音譯或亂碼、話被截斷，或用了上述以外的語言",
        },
    }


def judge(first: str, second: str) -> tuple[str, dict, float]:
    state = f"{HEKEE}\n{PREV}"
    t0 = time.perf_counter()
    scores = jev_nouls(state, {"one": plausible(first), "two": plausible(second)}, timeout=10)
    elapsed = time.perf_counter() - t0
    # 差不多時不動：照定稿送（呼叫端決定哪個是定稿）。
    if abs(scores["one"] - scores["two"]) < 0.2:
        return "tie", scores, elapsed
    return ("one" if scores["one"] > scores["two"] else "two"), scores, elapsed


out, ok, flips, lat = [], 0, 0, []
for interim, final, truth in CASES:
    picks = []
    for order in ("interim_first", "final_first"):
        a, b = (interim, final) if order == "interim_first" else (final, interim)
        pick, scores, elapsed = judge(a, b)
        lat.append(elapsed)
        chosen = "final" if pick == "tie" else ({"one": a, "two": b}[pick] == interim and "interim" or "final")
        picks.append(chosen)
        out.append({"interim": interim, "final": final, "truth": truth, "order": order,
                    "scores": scores, "chosen": chosen, "seconds": round(elapsed, 3)})
    correct = all(p == truth for p in picks) if truth != "either" else True
    ok += correct
    flips += picks[0] != picks[1]
    print(f"{'OK ' if correct else 'BAD'} {truth:7} picks={picks} | {interim!r} vs {final!r}", flush=True)

lat.sort()
print(f"\n正確 {ok}/{len(CASES)}，順序翻轉 {flips}/{len(CASES)}，延遲 p50 {lat[len(lat)//2]:.2f}s 最慢 {lat[-1]:.2f}s")
json.dump(out, open("/tmp/asr_judge.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
