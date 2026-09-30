"""日韓語音走 Gemini Live 串流辨識：語言提示對不對有多大差別（在 backend 容器內執行）。

用 edge-tts 合成（不是真人），照前台節奏每 0.1 秒送 3200 bytes，記最後暫定字幕與定稿。
"""
import asyncio, base64, json, os, re, subprocess
import edge_tts, websockets

URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
MODEL = os.environ.get("ASR_GEMINI_STREAM_MODEL", "gemini-3.5-transcribe-live")
SENTENCES = {
    "ja": ("ja-JP-NanamiNeural", [
        "このポンプの馬力はいくつですか？", "水中ポンプの最大揚程を教えてください。",
        "汚泥用のポンプはありますか？", "保証期間はどのくらいですか？",
        "こんにちは、あなたは誰ですか？", "ありがとうございました。",
    ]),
    "ko": ("ko-KR-SunHiNeural", [
        "이 펌프의 마력은 얼마입니까?", "수중 펌프의 최대 양정을 알려 주세요.",
        "오수용 펌프가 있나요?", "보증 기간은 얼마나 되나요?",
        "안녕하세요, 당신은 누구입니까?", "감사합니다.",
    ]),
}
HINTS = {
    "ja": [["ja-JP", "zh-TW"], ["zh-TW", "en-US", "es-ES"]],
    "ko": [["ko-KR", "zh-TW"], ["zh-TW", "en-US", "es-ES"]],
}


def cer(ref, hyp):
    norm = lambda t: re.sub(r"[\W_]+", "", t)
    ref, hyp = norm(ref), norm(hyp)
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / max(len(ref), 1)


async def pcm_of(text, voice, path):
    await edge_tts.Communicate(text, voice).save(path + ".mp3")
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", path + ".mp3",
                    "-ac", "1", "-ar", "16000", "-f", "s16le", path], check=True)
    return open(path, "rb").read()


async def stream(pcm, langs):
    async with websockets.connect(URL, additional_headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}) as ws:
        await ws.send(json.dumps({"setup": {"model": f"models/{MODEL}", "inputAudioTranscription": {"languageCodes": langs}}}))
        await ws.recv()
        interims, finals = [], []

        async def reader():
            async for raw in ws:
                c = json.loads(raw).get("serverContent", {})
                if t := (c.get("interimInputTranscription") or {}).get("text"):
                    interims.append(t)
                if t := (c.get("inputTranscription") or {}).get("text"):
                    finals.append(t.strip())

        task = asyncio.create_task(reader())
        silence = b"\0" * 3200
        for chunk in [silence] * 3 + [pcm[i:i + 3200] for i in range(0, len(pcm), 3200)] + [silence] * 20:
            await ws.send(json.dumps({"realtimeInput": {"audio": {"data": base64.b64encode(chunk).decode(), "mimeType": "audio/pcm;rate=16000"}}}))
            await asyncio.sleep(0.1)
        await asyncio.sleep(1.5)
        task.cancel()
        return (interims[-1] if interims else ""), " ".join(finals)


async def main():
    results = []
    for lang, (voice, sentences) in SENTENCES.items():
        for i, text in enumerate(sentences):
            pcm = await pcm_of(text, voice, f"/tmp/jk_{lang}{i}.pcm")
            for hints in HINTS[lang]:
                interim, final = await stream(pcm, hints)
                row = {"lang": lang, "hints": hints, "ref": text, "interim": interim, "final": final,
                       "cer": round(cer(text, final), 3)}
                results.append(row)
                print(f"{lang} {','.join(hints):18} cer={row['cer']:.2f} final={final!r} ref={text!r}", flush=True)
    json.dump(results, open("/tmp/jk_stream.json", "w"), ensure_ascii=False, indent=1)
    for lang in SENTENCES:
        for hints in HINTS[lang]:
            rows = [r for r in results if r["lang"] == lang and r["hints"] == hints]
            print(f"SUMMARY {lang} hints={','.join(hints)} mean_cer={sum(r['cer'] for r in rows)/len(rows):.3f}")

asyncio.run(main())
