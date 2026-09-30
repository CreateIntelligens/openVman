"""把專案詞表（ASR_PROMPT.md）放進對話提示，Brain 能不能自己把語音誤聽對回來（api 容器內執行）。

走正式的 build_chat_messages + run_agent_loop（fast 模式、只查知識庫），比較：
- none：現況提示
- glossary：同一份提示在回答語言那行前面插入 core/asr_glossary.glossary_line
不寫任何正式資料：用量記帳、檢索紀錄都換成空函式；不建 session。結果寫到 /tmp/asr_glossary.json。
"""
import importlib.util, json, sys, time
sys.path.insert(0, "/app")
import core.llm_client as llm_client
import memory.retrieval as retrieval
llm_client.record_usage_event = lambda *a, **k: None
retrieval.record_trace = lambda *a, **k: None
from core.agent_loop import run_agent_loop
from core.prompt_builder import build_chat_messages

spec = importlib.util.spec_from_file_location("core.asr_glossary", "/tmp/asr_glossary.py")
glossary = importlib.util.module_from_spec(spec); sys.modules["core.asr_glossary"] = glossary; spec.loader.exec_module(glossary)

P = "proj-0cc5c610b4"
# (語音辨識結果, 正確的專有名詞, 回答或查到的段落應出現的字)
MAPPINGS = "常見誤聽：UNI本、烏尼本→污泥泵；UBL→EUBL；DBX、低瓦→DIVA；一步→EUBL；奔騰（問泵浦時）→泵浦"
ONLY = sys.argv[1:] == ["mappings"]
CASES = [
    ("這臺奔騰的馬力是多少？", "泵浦", "HP"),
    ("UNI 本有幾種型號？", "污泥泵", "EUBL|DIVA"),
    ("沉睡泵最深可以放多深？", "沉水泵", "10"),
    ("UBL 和 DBX 在哪裡？", "EUBL|DIVA", "EUBL"),
    ("一步的馬力多少", "EUBL", "EUBL"),
    ("請問低瓦有攪拌器嗎", "DIVA", "DIVA"),
    ("哈波系列最大流量多少", "HIPPO", "HIPPO"),
    ("阿利蓋特可以絞碎什麼", "ALLIGATOR", "ALLIGATOR"),
    # 對照：本來就對的，不能被帶偏
    ("沉水泵最深可以放多深？", "沉水泵", "10"),
    ("奔騰電腦現在還有在賣嗎？", None, None),
    ("你好，請問你是誰？", None, None),
]


def run(text, with_glossary):
    ctx = {"project_id": P, "persona_id": "default", "session_id": "exp-asr-glossary", "metadata": {}}
    messages = build_chat_messages(text, ctx, [])
    if with_glossary:
        system = messages[0]["content"]
        marker = system.rfind("這一輪的回答語言：")
        line = glossary.glossary_line(P)
        if ONLY:
            line = line.replace("\n理解問題", f"\n{MAPPINGS}\n理解問題")
        messages[0]["content"] = system[:marker] + line + "\n\n" + system[marker:]
    t0 = time.perf_counter()
    result = run_agent_loop(messages, persona_id="default", project_id=P,
                            allow_forced_knowledge_search=True, reply_mode="fast")
    queries, found = [], ""
    for step in result.tool_steps:
        if step.get("name") == "search_knowledge":
            try:
                queries += json.loads(step.get("arguments") or "{}").get("queries", [])
            except ValueError:
                pass
            found += str(step.get("result", ""))
    return {"queries": queries, "found": found, "reply": result.reply, "seconds": round(time.perf_counter() - t0, 1)}


rows = []
settings = ("glossary",) if ONLY else ("none", "glossary")
cases = [c for c in CASES if c[0] in ("這臺奔騰的馬力是多少？", "UNI 本有幾種型號？", "UBL 和 DBX 在哪裡？", "一步的馬力多少", "奔騰電腦現在還有在賣嗎？", "你好，請問你是誰？")] if ONLY else CASES
for heard, term, evidence in cases:
    for setting in settings:
        r = run(heard, setting == "glossary")
        term_ok = None if term is None else any(t in " ".join(r["queries"]) + r["reply"] for t in term.split("|"))
        evidence_ok = None if evidence is None else any(t in r["found"] for t in evidence.split("|"))
        rows.append({"heard": heard, "setting": setting, "term_ok": term_ok, "evidence_ok": evidence_ok, **r,
                     "found": r["found"][:600]})
        print(f"{setting:8} term={term_ok!s:5} evidence={evidence_ok!s:5} {r['seconds']:4}s | {heard} | queries={r['queries']} | reply={r['reply'][:90]!r}", flush=True)
json.dump(rows, open("/tmp/asr_glossary_mappings.json" if ONLY else "/tmp/asr_glossary.json", "w"), ensure_ascii=False, indent=1)
for setting in ("none", "glossary"):
    rs = [r for r in rows if r["setting"] == setting and r["term_ok"] is not None]
    misheard = [r for r in rs if r["heard"] != "沉水泵最深可以放多深？"]
    print(f"SUMMARY {setting}: 誤聽 {len(misheard)} 句中，查詢或回答用上正確名詞 {sum(r['term_ok'] for r in misheard)}、查到對的段落 {sum(r['evidence_ok'] for r in misheard)}")
