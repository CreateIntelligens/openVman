"""Gemini transcribe-live 會不會參考 systemInstruction 裡的背景知識（backend 容器內執行）。

同一段合成語音，比較：不給、給一段專案背景＋常見詞。錯字多的是「泵」相關名詞。
"""
import asyncio, base64, json, os, re, subprocess
import edge_tts, websockets

URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
MODEL = os.environ.get("ASR_GEMINI_STREAM_MODEL", "gemini-3.5-transcribe-live")
CONTEXT = (
    "這是鶴記企業與億發泵浦（EVAK）的產品諮詢對話，使用者會問沉水泵、污水泵、污泥泵、泥漿泵、"
    "排水泵的規格、馬力、揚程與型號。常見詞：泵浦、沉水泵、污泥泵、污水泵、揚程、馬力、"
    "著脫座、EUBL、EUS、DIVA、HIPPO、LEOPARD、ALLIGATOR。"
)
SENTENCES = [
    ("zh-TW-HsiaoChenNeural", "這台泵浦的馬力是多少？", ["zh-TW", "en-US", "es-ES"]),
    ("zh-TW-HsiaoChenNeural", "污泥泵有幾種型號？", ["zh-TW", "en-US", "es-ES"]),
    ("zh-TW-HsiaoChenNeural", "沉水泵最深可以放多深？", ["zh-TW", "en-US", "es-ES"]),
    ("zh-TW-YunJheNeural", "我想找一台排水泵，揚程要二十米。", ["zh-TW", "en-US", "es-ES"]),
    ("zh-TW-YunJheNeural", "EUBL 跟 DIVA 差在哪裡？", ["zh-TW", "en-US", "es-ES"]),
    ("zh-TW-HsiaoChenNeural", "你好，請問你是誰？", ["zh-TW", "en-US", "es-ES"]),
    ("zh-TW-HsiaoChenNeural", "今天天氣很好。", ["zh-TW", "en-US", "es-ES"]),
    ("en-US-GuyNeural", "Who am I?", ["zh-TW", "en-US", "es-ES"]),
    ("es-ES-ElviraNeural", "¿Cuántos caballos tiene la bomba de lodos?", ["zh-TW", "en-US", "es-ES"]),
]


def cer(ref, hyp):
    n = lambda t: re.sub(r"[\W_]+", "", t).lower().replace("臺", "台")
    ref, hyp = n(ref), n(hyp)
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return round(prev[-1] / max(len(ref), 1), 2)


async def pcm_of(text, voice):
    mp3 = b"".join([c["data"] async for c in edge_tts.Communicate(text, voice).stream() if c["type"] == "audio"])
    return subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", "16000",
                           "-f", "s16le", "pipe:1"], input=mp3, capture_output=True, check=True).stdout


async def stream(pcm, langs, context):
    setup = {"model": f"models/{MODEL}", "inputAudioTranscription": {"languageCodes": langs}}
    if context:
        setup["systemInstruction"] = {"parts": [{"text": context}]}
    async with websockets.connect(URL, additional_headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}) as ws:
        await ws.send(json.dumps({"setup": setup}))
        first = json.loads(await ws.recv())
        if "setupComplete" not in first:
            return f"SETUP REJECTED {str(first)[:160]}"
        finals = []

        async def reader():
            async for raw in ws:
                c = json.loads(raw).get("serverContent", {})
                if t := (c.get("inputTranscription") or {}).get("text"):
                    finals.append(t.strip())

        task = asyncio.create_task(reader())
        silence = b"\0" * 3200
        for chunk in [silence] * 3 + [pcm[i:i + 3200] for i in range(0, len(pcm), 3200)] + [silence] * 20:
            await ws.send(json.dumps({"realtimeInput": {"audio": {"data": base64.b64encode(chunk).decode(), "mimeType": "audio/pcm;rate=16000"}}}))
            await asyncio.sleep(0.1)
        await asyncio.sleep(1.5)
        task.cancel()
        return " ".join(finals)


async def main():
    rows = []
    for voice, text, langs in SENTENCES:
        pcm = await pcm_of(text, voice)
        for label, context in (("none", ""), ("context", CONTEXT)):
            for rep in range(2):
                heard = await stream(pcm, langs, context)
                rows.append({"text": text, "setting": label, "rep": rep, "heard": heard, "cer": cer(text, heard)})
                print(f"{label:8} cer={cer(text, heard):.2f} heard={heard!r} ref={text!r}", flush=True)
    json.dump(rows, open("/tmp/ctx_probe.json", "w"), ensure_ascii=False, indent=1)
    for label in ("none", "context"):
        rs = [r for r in rows if r["setting"] == label]
        print(f"SUMMARY {label}: mean cer {sum(r['cer'] for r in rs)/len(rs):.3f}, exact {sum(r['cer']==0 for r in rs)}/{len(rs)}")

asyncio.run(main())
