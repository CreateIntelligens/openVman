import json, sys, time, uuid
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, "/app")
import memory.retrieval as retrieval
retrieval.record_trace = lambda *a, **k: None
from core.prompt_builder import build_chat_messages
from core.agent_loop import run_agent_loop
from config import get_settings
P = "dev-c0c8fdff34"
qs = json.load(open("/tmp/chat_queries.json"))
print("version", get_settings().resolved_embedding_active_version)
def run(q):
    ctx = {"persona_id": "default", "project_id": P, "session_id": f"emb-ab-{uuid.uuid4().hex[:8]}", "channel": "web", "locale": "zh-TW", "metadata": {}}
    t = time.perf_counter()
    try:
        r = run_agent_loop(build_chat_messages(q["q"], ctx, []), "default", P, allow_forced_knowledge_search=True, reply_mode="fast")
        return {**q, "reply": r.reply, "ms": round((time.perf_counter() - t) * 1000)}
    except Exception as e:
        return {**q, "reply": "", "error": repr(e)[:200]}
with ThreadPoolExecutor(4) as ex:
    out = list(ex.map(run, qs))
json.dump(out, open("/tmp/chat_out.json", "w"), ensure_ascii=False)
print(len(out), "errors", sum("error" in o for o in out))
