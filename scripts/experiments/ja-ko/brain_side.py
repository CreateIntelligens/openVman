"""日韓在 Brain 這一側：語言判斷、鶴記知識庫檢索、Jev 定稿判斷（api 容器內，唯讀）。

注意：容器裡是正式部署的程式；日韓的文字判斷要等新版部署後才有，這裡用 repo 的
規則函式（掛進 /tmp/new_language_detect.py）另外算一次。
"""
import importlib.util, json, sys
sys.path.insert(0, "/app")
import memory.retrieval as retrieval
retrieval.record_trace = lambda *a, **k: None
from memory.embedder import get_embedder
from core.jev_client import jev_nouls

spec = importlib.util.spec_from_file_location("new_ld", "/tmp/new_language_detect.py")
new_ld = importlib.util.module_from_spec(spec); spec.loader.exec_module(new_ld)

HEKEE = "proj-0cc5c610b4"
Q = [
    ("ja", "このポンプの馬力はいくつですか？", "EUBL|DIVA|HP"),
    ("ja", "50EUBLの固形物通過径は何ミリですか？", "EUBL"),
    ("ja", "DIVA PROには攪拌機がありますか？", "DIVA PRO"),
    ("ja", "水温の制限は何度ですか？", "40"),
    ("ko", "이 펌프의 마력은 얼마입니까?", "EUBL|DIVA|HP"),
    ("ko", "50EUBL의 고형물 통과 크기는 몇 mm입니까?", "EUBL"),
    ("ko", "DIVA PRO에는 교반기가 있습니까?", "DIVA PRO"),
    ("ko", "수온 제한은 몇 도입니까?", "40"),
]
emb = get_embedder()
out = {"detect": [], "retrieval": [], "jev": []}
print("== 語言判斷（新規則）")
for lang, q, _ in Q + [("zh", "污泥泵有幾匹馬力？", ""), ("es", "¿Cuántos caballos tiene la bomba?", "")]:
    got = new_ld.detect_language(q)
    out["detect"].append({"q": q, "expected": lang, "got": got})
    print(f"  {got == lang and 'OK ' or 'BAD'} {lang}->{got} {q}")
print("== 鶴記檢索（門檻 1.0，現有中英西文件）")
for lang, q, expect in Q:
    vec = list(map(float, emb.encode([q])[0]))
    rows = retrieval.search_records("knowledge", vec, top_k=3, query_text=q, query_type="hybrid",
                                    project_id=HEKEE, min_similarity=0.5)
    best = min([r.get("_distance") or 9 for r in rows] or [9])
    hit = any(any(k in str(r.get("text", "")) for k in expect.split("|")) for r in rows)
    out["retrieval"].append({"q": q, "best": best, "n": len(rows), "hit": hit,
                             "paths": [r.get("path") for r in rows]})
    print(f"  {'hit ' if hit else 'MISS'} best={best:.3f} n={len(rows)} {q} {[r.get('path') for r in rows]}")
print("== Jev 定稿判斷（情境：日文或韓文專案）")
names = {"ja": "日文、繁體中文", "ko": "韓文"}
pairs = [
    ("ja", "汚泥用のポンプはありますか？", "おでん用のポンプはありますか？", "interim"),
    ("ja", "こんにちは、あなたは誰ですか？", "こんにちは、あなたはダレですか", "either"),
    ("ja", "このポンプの馬", "このポンプの馬力はいくつですか？", "final"),
    ("ja", "水温の制限は何度ですか", "水溫限制是幾度", "interim"),
    ("ko", "이 펌프의 마력은 얼마입니까?", "이 泵의 마력은 얼마입니까?", "interim"),
    ("ko", "안녕하세요 당신은", "안녕하세요, 당신은 누구입니까?", "final"),
    ("ko", "감사합니다", "看撒哈姆尼達", "interim"),
]
def plausible(text):
    return {"instructions": f"語音辨識把使用者的話轉成「{text}」，這像是正確辨識出來的一句話嗎？",
            "criteria": {"true": "通順、像真人會說的話，是上述語言之一；跟專案無關的閒聊或測試也算。專有名詞（型號、品牌）拼對",
                         "false": "有聽錯的同音字（例如把型號聽成別的詞）、無意義的音譯或亂碼、話被截斷，或用了上述以外的語言"}}
for lang, interim, final, truth in pairs:
    state = f"專案：EVAK 泵浦產品諮詢。這個專案的使用者可能說：{names[lang]}。"
    s = jev_nouls(state, {"interim": plausible(interim), "final": plausible(final)}, timeout=10)
    chosen = "interim" if s["interim"] - s["final"] >= 0.2 else "final"
    ok = truth == "either" or chosen == truth
    out["jev"].append({"lang": lang, "interim": interim, "final": final, "truth": truth, "scores": s, "chosen": chosen})
    print(f"  {'OK ' if ok else 'BAD'} {truth:7} chose={chosen:7} {s} | {interim} vs {final}")
json.dump(out, open("/tmp/jk_brain.json", "w"), ensure_ascii=False, indent=1)
