"""比較知識庫距離門檻：相關題命中率與無關題雜訊（唯讀，不寫召回紀錄）。"""
import json, sys
sys.path.insert(0, "/app")
import memory.retrieval as retrieval
retrieval.record_trace = lambda *a, **k: None
from memory.embedder import get_embedder

HEKEE, HOSP = "proj-0cc5c610b4", "proj-b85afb8bb6"
# (語言, 問題, 正確段落應含的字；None = 無關題)
Q = [
 ("zh","50EUBL 的固體通過粒徑是多少？","EUBL"),("zh","污泥泵有幾匹馬力？","EUBL|DIVA"),
 ("zh","DIVA PRO 有攪拌器嗎？","DIVA PRO"),("zh","HIPPO 是什麼樣的泵？","HIPPO"),
 ("zh","LEOPARD 切碎泵的轉速多少？","LEOPARD"),("zh","ALLIGATOR 可以處理什麼？","ALLIGATOR"),
 ("zh","沉水泵最深可以放多深？","10"),("zh","水溫限制是幾度？","40"),
 ("zh","絕緣等級是什麼？","Class|絕緣"),("zh","著脫座要怎麼選？","QD|著脫"),
 ("zh","EUS 可以改成殘水泵嗎？","EUS"),("zh","你們公司電話幾號？","26233556"),
 ("en","What is the solids passage of the 50EUBL?","EUBL"),("en","How much horsepower does the sludge pump have?","EUBL|DIVA"),
 ("en","Does DIVA PRO have an agitator?","DIVA PRO"),("en","What kind of pump is HIPPO?","HIPPO"),
 ("en","What speed does the LEOPARD cutter pump run at?","LEOPARD"),("en","What can the ALLIGATOR handle?","ALLIGATOR"),
 ("en","How deep can the submersible pump go?","10"),("en","What is the water temperature limit?","40"),
 ("en","What insulation class is used?","Class|insulation"),("en","How do I choose a duck foot?","QD|duck foot|Duck Foot"),
 ("en","Can the EUS be converted to a residue pump?","EUS"),("en","What is your company phone number?","26233556"),
 ("es","¿Cuál es el paso de sólidos de la 50EUBL?","EUBL"),("es","¿Cuántos caballos tiene la bomba de lodos?","EUBL|DIVA"),
 ("es","¿La DIVA PRO tiene agitador?","DIVA PRO"),("es","¿Qué tipo de bomba es HIPPO?","HIPPO"),
 ("es","¿A qué velocidad gira la bomba cortadora LEOPARD?","LEOPARD"),("es","¿Qué puede manejar la ALLIGATOR?","ALLIGATOR"),
 ("es","¿A qué profundidad se puede sumergir la bomba?","10"),("es","¿Cuál es el límite de temperatura del agua?","40"),
 ("es","¿Qué clase de aislamiento usa?","Clase|aislamiento|Class"),("es","¿Cómo elijo la base de acoplamiento?","QD|acoplamiento"),
 ("es","¿Se puede convertir la EUS en bomba de achique residual?","EUS"),("es","¿Cuál es el teléfono de la empresa?","26233556"),
 ("zh","今天天氣如何？",None),("zh","你好",None),("zh","講個笑話",None),
 ("en","What's the weather tomorrow?",None),("en","hi there",None),("en","Tell me a joke",None),
 ("es","¿Qué tiempo hará mañana?",None),("es","hola",None),("es","Cuéntame un chiste",None),
]
HOSP_Q = [("zh","今天天氣如何？"),("zh","你好"),("zh","講個笑話"),("en","hi there")]

emb = get_embedder()
def run(project, lang, q, cutoff):
    vec = list(map(float, emb.encode([q])[0]))
    rows = retrieval.search_records("knowledge", vec, top_k=5, query_text=q, query_type="hybrid",
                                    project_id=project, language=lang, min_similarity=1 - cutoff / 2)
    return [(r.get("_distance"), r.get("path"), str(r.get("text",""))) for r in rows]

out = {}
for cutoff in (0.85, 1.0):
    hit = miss = noise = 0; detail = []
    for lang, q, expect in Q:
        rows = run(HEKEE, lang, q, cutoff)
        if expect is None:
            noise += len(rows)
            detail.append((lang, q, "NOISE" if rows else "clean", [(round(d or -1, 3), p) for d, p, _ in rows]))
        else:
            ok = any(any(k in t for k in expect.split("|")) for _, _, t in rows[:3])
            hit += ok; miss += not ok
            detail.append((lang, q, "hit" if ok else "MISS", [(round(d or -1, 3), p) for d, p, _ in rows[:3]]))
    hosp_noise = sum(len(run(HOSP, l, q, cutoff)) for l, q in HOSP_Q)
    out[cutoff] = detail
    print(f"cutoff {cutoff}: 相關題命中 {hit}/{hit+miss}，鶴記無關題雜訊 {noise} 段，醫院無關題雜訊 {hosp_noise} 段")
json.dump({str(k): v for k, v in out.items()}, open("/tmp/hekee/cutoff_eval.json", "w"), ensure_ascii=False, indent=1)
