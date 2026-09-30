"""語音辨識結果＋專案詞表交給快速模型修同音錯字：修得回來嗎？會不會改壞？（api 容器內，不寫資料）"""
import json, sys, time
sys.path.insert(0, "/app")
from core.llm_client import generate_chat_reply

GLOSSARY = ("鶴記企業、億發泵浦、EVAK、沉水泵、排水泵、污水泵、污泥泵、泥漿泵、殘水泵、絞碎泵、切割泵、EUS、EDW、"
            "EUB-M、EUBL、DIVA、DIVA PRO、HIPPO、STEEL、ALLIGATOR、LEOPARD、Q.D.C.、自動著脫裝置、揚程、流量、LPM、"
            "機械軸封、葉輪、耐磨板、Yamada、過載保護器、泵浦")
SYSTEM = (
    "你是語音辨識的校正器。下面是一句語音辨識結果，可能把專有名詞聽成同音或近音的別的詞。"
    f"這個專案的專有名詞：{GLOSSARY}。\n"
    "規則：只有在某個詞明顯是上面專有名詞的同音、近音誤聽時才改成該專有名詞；其他字一個都不要動，"
    "不要改標點、不要改寫句子、不要翻譯、不要回答問題。沒有要改的就原封不動輸出。只輸出校正後的句子。"
)
CASES = [
    ("這臺奔騰的馬力是多少？", "這台泵浦的馬力是多少？"),
    ("UNI 本有幾種型號？", "污泥泵有幾種型號？"),
    ("烏尼本有幾種型號?", "污泥泵有幾種型號？"),
    ("沉睡泵最深可以放多深？", "沉水泵最深可以放多深？"),
    ("沉睡笨最深可以放多深？", "沉水泵最深可以放多深？"),
    ("UBL 和 DBX 在哪裡？", "EUBL 跟 DIVA 差在哪裡？"),
    ("一步的馬力多少", "EUBL 的馬力多少"),
    ("請問低瓦有攪拌器嗎", "請問 DIVA 有攪拌器嗎"),
    # 不該改的
    ("你好，請問你是誰？", None),
    ("今天天氣很好。", None),
    ("Who am I?", None),
    ("¿Cuántos caballos tiene la bomba de lodos?", None),
    ("我想找一臺排水泵，揚程要 20 米。", None),
    ("奔騰電腦現在還有在賣嗎？", None),
    ("이 펌프의 마력은 얼마입니까?", None),
]
rows = []
for heard, truth in CASES:
    t0 = time.perf_counter()
    fixed = generate_chat_reply([{"role": "system", "content": SYSTEM}, {"role": "user", "content": heard}],
                                model_override="gemini-3.5-flash-lite", privacy_source="unknown").strip()
    ms = round((time.perf_counter() - t0) * 1000)
    expect = truth or heard
    ok = fixed.replace("臺", "台").rstrip("？?。") == expect.replace("臺", "台").rstrip("？?。")
    rows.append({"heard": heard, "expected": expect, "fixed": fixed, "ok": ok, "ms": ms})
    print(f"{'OK ' if ok else 'BAD'} {ms:5}ms {heard!r} -> {fixed!r}" + ("" if ok else f"  (want {expect!r})"), flush=True)
json.dump(rows, open("/tmp/glossary_fix.json", "w"), ensure_ascii=False, indent=1)
fix = [r for r in rows[:8]]; keep = rows[8:]
print(f"\n該修的 {sum(r['ok'] for r in fix)}/{len(fix)}，不該改的保持原樣 {sum(r['ok'] for r in keep)}/{len(keep)}，延遲 p50 {sorted(r['ms'] for r in rows)[len(rows)//2]}ms")
