"""Gemini 3.5 transcribe live 多語實測：同一組 15 句（英西日韓＋中），兩種語言提示，一次一路。"""
import asyncio, base64, json, sys
from pathlib import Path
import websockets
ROOT = Path(__file__).resolve().parents[4]; sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from r2t2_lang import CASES, synth  # noqa: E402  (只匯入，不跑)
env = {}
for f in (ROOT / ".env", ROOT / "backend/.env"):
    if f.exists():
        env.update(dict(l.split("=", 1) for l in f.read_text().splitlines() if "=" in l and not l.startswith("#")))
KEY = env["GEMINI_API_KEY"].strip()
URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
MODEL = env.get("ASR_GEMINI_STREAM_MODEL", "gemini-3.5-transcribe-live").strip()
HINTS = {"all5": ["zh-TW", "en-US", "es-ES", "ja-JP", "ko-KR"], "zh_en_es": ["zh-TW", "en-US", "es-ES"]}

async def stream(pcm, codes):
    async with websockets.connect(URL, additional_headers={"x-goog-api-key": KEY}, max_size=4 << 20, open_timeout=10) as ws:
        await ws.send(json.dumps({"setup": {"model": f"models/{MODEL}", "inputAudioTranscription": {"languageCodes": codes}}}))
        first = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if "setupComplete" not in first:
            return f"<setup {str(first)[:100]}>"
        finals = []
        async def reader():
            async for raw in ws:
                c = json.loads(raw).get("serverContent") or {}
                if t := (c.get("inputTranscription") or {}).get("text"):
                    finals.append(t.strip())
        task = asyncio.create_task(reader())
        for i in range(0, len(pcm), 3200):
            await ws.send(json.dumps({"realtimeInput": {"audio": {"mimeType": "audio/pcm;rate=16000", "data": base64.b64encode(pcm[i:i+3200]).decode()}}}))
            await asyncio.sleep(0.1)
        for _ in range(15):
            await ws.send(json.dumps({"realtimeInput": {"audio": {"mimeType": "audio/pcm;rate=16000", "data": base64.b64encode(b"\0" * 3200).decode()}}}))
            await asyncio.sleep(0.1)
        await ws.send(json.dumps({"realtimeInput": {"audioStreamEnd": True}}))
        await asyncio.sleep(4)
        task.cancel()
        return " ".join(finals) or "<no final>"

async def main():
    rows = []
    print("model", MODEL, flush=True)
    for lang, (_, voice, texts) in CASES.items():
        for t in texts:
            pcm = await asyncio.to_thread(synth, voice, t)
            for hint, codes in HINTS.items():
                out = await stream(pcm, codes)
                rows.append({"lang": lang, "hint": hint, "ref": t, "out": out})
                print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    (Path(__file__).with_name("gemini_lang_results.json")).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
if __name__ == "__main__":
    asyncio.run(main())
