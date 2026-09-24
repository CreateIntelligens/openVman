import asyncio, base64, json, sys, time
sys.path.insert(0, "/app")
from internal_routes import _build_live_system_instruction
from live.gemini_live import GeminiLiveSession
from memory.memory import delete_session_for_project
P = "proj-b85afb8bb6"
rows = [l.rstrip("\n").split("\t") for l in open("/tmp/taigi/sentences.tsv", encoding="utf-8")]
async def run(sid_key, tw, zh):
    pcm = open(f"/tmp/taigi/{sid_key}.pcm", "rb").read()
    ev = {"user": [], "text": [], "audio": 0, "done": asyncio.Event(), "t_first": None}
    async def sink(e):
        if e.get("event") == "user_transcription": ev["user"].append(e.get("text", ""))
        elif e.get("event") == "server_stream_chunk":
            if e.get("text"): ev["text"].append(e["text"])
            if e.get("audio_base64"):
                ev["audio"] += 1
                if ev["t_first"] is None: ev["t_first"] = time.time()
            if e.get("is_final") and ev["audio"]: ev["done"].set()
    sid = f"taigi-exp-{sid_key}-{int(time.time())}"
    s = GeminiLiveSession(relay_session_id=sid, client_id=sid, project_id=P, session_id=sid,
        system_instruction=_build_live_system_instruction("default", P, session_id=sid), event_sink=sink)
    await s.ensure_connected()
    for i in range(0, len(pcm), 3200):
        await s.send_realtime_input(base64.b64encode(pcm[i:i+3200]).decode(), "audio/pcm;rate=16000"); await asyncio.sleep(0.1)
    t_end = time.time()
    for _ in range(15):
        await s.send_realtime_input(base64.b64encode(b"\0"*3200).decode(), "audio/pcm;rate=16000"); await asyncio.sleep(0.1)
    try: await asyncio.wait_for(ev["done"].wait(), 45)
    except asyncio.TimeoutError: pass
    await s.close(); delete_session_for_project(P, sid)
    lat = round(ev["t_first"] - t_end, 2) if ev["t_first"] else None
    return {"heard": "".join(ev["user"]), "reply": "".join(ev["text"])[:160], "latency": lat}
async def main():
    out = {}
    for sid_key, tw, zh in rows:
        r = await run(sid_key, tw, zh); out[sid_key] = r
        print(f"{sid_key} 意思:{zh}\n   收音: {r['heard']}\n   回覆: {r['reply']}\n   延遲: {r['latency']}s")
    json.dump(out, open("/tmp/taigi/live.json", "w"), ensure_ascii=False, indent=1)
asyncio.run(main())
