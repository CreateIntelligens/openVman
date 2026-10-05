"""R2T2 串流多語實測：每種語言 3 句 edge-tts 合成語音 × 三種 language 設定（指定、zhen、Chinese），一次一路。

    python3 scripts/experiments/r2t2/multilang/r2t2_lang.py 37   # .37（ASR_R2T2_STREAM_URL）
    python3 scripts/experiments/r2t2/multilang/r2t2_lang.py 35   # .35（ASR_R2T2_DEV_STREAM_URL）
"""
import asyncio, json, sys, uuid
from pathlib import Path
import websockets
ROOT = Path(__file__).resolve().parents[4]; sys.path.insert(0, str(ROOT))
from scripts.voice_e2e.run import to_pcm
env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l and not l.startswith("#"))
HOST = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("35", "37") else "37"
URL, KEY = ((env["ASR_R2T2_DEV_STREAM_URL"], env["ASR_R2T2_DEV_SECRET_KEY"]) if HOST == "35"
            else (env["ASR_R2T2_STREAM_URL"], env["ASR_R2T2_SECRET_KEY"]))
CASES = {
    "zh": ("Chinese", "edge-tts:zh-TW-HsiaoChenNeural", ["請問沉水泵最深可以放多深？", "工地要抽泥漿，推薦哪一款？", "你們的營業時間是幾點？"]),
    "en": ("English", "edge-tts:en-US-JennyNeural", ["How deep can the submersible pump go?", "Which slurry pump do you recommend for a construction site?", "What are your business hours?"]),
    "es": ("Spanish", "edge-tts:es-ES-ElviraNeural", ["¿Qué profundidad máxima soporta la bomba sumergible?", "¿Qué bomba de lodos recomiendan para una obra?", "¿Cuál es su horario de atención?"]),
    "ja": ("Japanese", "edge-tts:ja-JP-NanamiNeural", ["水中ポンプはどのくらいの深さまで使えますか？", "工事現場で泥水を吸うにはどのポンプがおすすめですか？", "営業時間は何時から何時までですか？"]),
    "ko": ("Korean", "edge-tts:ko-KR-SunHiNeural", ["수중 펌프는 얼마나 깊이 설치할 수 있나요?", "공사 현장에서 진흙물을 퍼내려면 어떤 펌프가 좋나요?", "영업 시간이 어떻게 되나요?"]),
}

def synth(voice, text):
    import edge_tts
    async def go():
        buf = b""
        async for chunk in edge_tts.Communicate(text, voice.partition(":")[2]).stream():
            if chunk["type"] == "audio": buf += chunk["data"]
        return buf
    return to_pcm(asyncio.get_event_loop().run_until_complete(go()) if False else asyncio.run(go()), 0.0)

async def stream(pcm, language):
    header = {"channels": 1, "sample_rate": 16000, "requestId": str(uuid.uuid4()), "language": language,
              "output_script": "traditional", "use_vad": True, "secret_key": KEY, "system_prompt": ""}
    text, used = "", None
    async with websockets.connect(URL, open_timeout=10) as ws:
        await ws.send(json.dumps(header))
        hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
        used = hello.get("language") or hello
        async def reader():
            nonlocal text
            async for raw in ws:
                m = json.loads(raw)
                if m.get("status") == "error":
                    text += f"<error {m.get('msg')}>"; return
                msg = m.get("msg", {})
                if msg.get("reset") and msg.get("final_text"):
                    text = msg["final_text"]; return
                text += msg.get("text", "")
                if msg.get("reset"): return
        task = asyncio.create_task(reader())
        for i in range(0, len(pcm), 5120):
            await ws.send(pcm[i:i + 5120]); await asyncio.sleep(0.16)
        for _ in range(10):
            await ws.send(b"\0" * 5120); await asyncio.sleep(0.16)
        await ws.send("YOUDAO_ONETIME_ASR_STREAM_EOS")
        try:
            await asyncio.wait_for(task, 15)
        except asyncio.TimeoutError:
            text += "<no final>"
    return text, used

async def main():
    rows = []
    for lang, (name, voice, texts) in CASES.items():
        for t in texts:
            pcm = await asyncio.to_thread(synth, voice, t)
            for setting in (name, "zhen", "Chinese"):
                out, used = await stream(pcm, setting)
                rows.append({"lang": lang, "setting": setting, "ref": t, "out": out, "server_language": used})
                print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    (Path(__file__).with_name(f"r2t2_lang_results_{HOST}.json")).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
if __name__ == "__main__":
    asyncio.run(main())
