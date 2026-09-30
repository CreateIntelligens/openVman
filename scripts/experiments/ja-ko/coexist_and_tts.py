"""中韓並存時的串流辨識（含 Jev 定稿判斷），以及五家 TTS 念日韓文（在 backend 容器內執行）。

1. 韓文 10 句、中文 6 句（edge-tts 原生聲音），提示 [ko-KR, zh-TW] 與 [zh-TW, ko-KR] 各跑一次；
   定稿跟暫定字幕不同時打正式的 Brain /brain/internal/asr-judge，看最後送出的字對不對。
2. Gemini TTS、Edge-TTS（預設聲音與日韓原生聲音）、IndexTTS、VoxCPM、CosyVoice 念日文 3 句、
   韓文 3 句、中文 1 句；把音檔用 Gemini 串流辨識轉回文字算字錯率（聽不聽得懂）。
結果寫到 /tmp/jk2.json。語音都是合成的。
"""
import asyncio, base64, json, os, re, subprocess, sys, time
sys.path.insert(0, "/app")
import edge_tts, httpx, websockets

from app.config import get_tts_config
from app.providers.base import SynthesizeRequest
from app.service import TTSRouterService

URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
MODEL = os.environ.get("ASR_GEMINI_STREAM_MODEL", "gemini-3.5-transcribe-live")
KO = ["이 펌프의 마력은 얼마입니까?", "수중 펌프의 최대 양정을 알려 주세요.", "오수용 펌프가 있나요?",
      "보증 기간은 얼마나 되나요?", "안녕하세요, 당신은 누구입니까?", "감사합니다.",
      "배수 펌프 가격이 궁금합니다.", "모터가 과열되면 어떻게 하나요?", "이 제품은 한국에서 구매할 수 있나요?",
      "설치 방법을 설명해 주세요."]
ZH = ["這台泵浦的馬力是多少？", "污泥泵有幾種型號？", "保固期間多久？",
      "你好，請問你是誰？", "謝謝你的說明。", "沉水泵最深可以放多深？"]
JA = ["このポンプの馬力はいくつですか？", "保証期間はどのくらいですか？", "ありがとうございました。"]


def norm(t):
    return re.sub(r"[\W_]+", "", t).lower()


def cer(ref, hyp):
    ref, hyp = norm(ref), norm(hyp)
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return round(prev[-1] / max(len(ref), 1), 3)


def to_pcm(data: bytes, content_type: str, sample_rate: int) -> bytes:
    raw = "pcm" in content_type or "l16" in content_type.lower()
    args = ["ffmpeg", "-nostdin", "-loglevel", "error"]
    if raw:
        args += ["-f", "s16le", "-ar", str(sample_rate), "-ac", "1"]
    args += ["-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"]
    return subprocess.run(args, input=data, capture_output=True, check=True).stdout


async def edge_pcm(text, voice):
    chunks = b"".join([c["data"] async for c in edge_tts.Communicate(text, voice).stream() if c["type"] == "audio"])
    return to_pcm(chunks, "audio/mpeg", 24000)


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
        return (interims[-1].strip() if interims else ""), " ".join(finals)


async def judge(routes, interim, final):
    cfg = get_tts_config()
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.post(f"{cfg.brain_url.rstrip('/')}/brain/internal/asr-judge",
                              json={"project_id": "default", "languages": routes, "interim": interim, "final": final},
                              headers={"X-Internal-Token": cfg.gateway_internal_token})
        return r.json()


async def coexist():
    rows = []
    for lang, voice, sentences in (("ko", "ko-KR-SunHiNeural", KO), ("zh", "zh-TW-HsiaoChenNeural", ZH)):
        for text in sentences:
            pcm = await edge_pcm(text, voice)
            for hints, routes in ((["ko-KR", "zh-TW"], ["ko", "zh"]), (["zh-TW", "ko-KR"], ["zh", "ko"])):
                interim, final = await stream(pcm, hints)
                sent, verdict = final, None
                if interim and norm(interim) != norm(final):
                    verdict = await judge(routes, interim, final)
                    sent = verdict.get("text") or final
                row = {"lang": lang, "hints": hints, "ref": text, "interim": interim, "final": final,
                       "sent": sent, "cer_final": cer(text, final), "cer_sent": cer(text, sent),
                       "judge": verdict}
                rows.append(row)
                print(f"[coexist] {lang} {','.join(hints):12} final={row['cer_final']:.2f} sent={row['cer_sent']:.2f} "
                      f"{'JUDGED ' + str(verdict.get('chosen')) if verdict else ''} | {final!r} -> {sent!r}", flush=True)
    return rows


async def tts_roundtrip():
    router = TTSRouterService()
    providers = {
        "gemini": router._gemini, "indextts": router._indextts, "voxcpm": router._voxcpm,
        "cosyvoice": router._cosyvoice, "edge-default": router._edge,
    }
    cases = [("ja", "ja-JP", t) for t in JA] + [("ko", "ko-KR", t) for t in KO[:3]] + [("zh", "zh-TW", ZH[0])]
    rows = []
    for name, adapter in providers.items():
        for lang, hint, text in cases:
            t0 = time.monotonic()
            try:
                res = await asyncio.to_thread(adapter.synthesize, SynthesizeRequest(text=text, locale=hint))
                pcm = to_pcm(res.audio_bytes, res.content_type, res.sample_rate)
                heard = (await stream(pcm, [hint]))[1]
                row = {"provider": name, "lang": lang, "ref": text, "heard": heard, "cer": cer(text, heard),
                       "seconds": round(time.monotonic() - t0, 1)}
            except Exception as exc:  # noqa: BLE001
                row = {"provider": name, "lang": lang, "ref": text, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
            rows.append(row)
            print(f"[tts] {name:12} {lang} {row.get('cer', 'ERR')} heard={row.get('heard', row.get('error'))!r}", flush=True)
    for lang, voice in (("ja", "ja-JP-NanamiNeural"), ("ko", "ko-KR-SunHiNeural")):
        for text in (JA if lang == "ja" else KO[:3]):
            pcm = await edge_pcm(text, voice)
            heard = (await stream(pcm, ["ja-JP" if lang == "ja" else "ko-KR"]))[1]
            rows.append({"provider": "edge-native", "lang": lang, "ref": text, "heard": heard, "cer": cer(text, heard)})
            print(f"[tts] edge-native  {lang} {cer(text, heard)} heard={heard!r}", flush=True)
    return rows


async def main():
    out = {"coexist": await coexist(), "tts": await tts_roundtrip()}
    json.dump(out, open("/tmp/jk2.json", "w"), ensure_ascii=False, indent=1)
    print("\n== 中韓並存")
    for lang in ("ko", "zh"):
        for hints in (["ko-KR", "zh-TW"], ["zh-TW", "ko-KR"]):
            rs = [r for r in out["coexist"] if r["lang"] == lang and r["hints"] == hints]
            print(f"  {lang} {','.join(hints):12} 定稿全對 {sum(r['cer_final'] == 0 for r in rs)}/{len(rs)}，送出全對 {sum(r['cer_sent'] == 0 for r in rs)}/{len(rs)}，平均 CER 定稿 {sum(r['cer_final'] for r in rs)/len(rs):.3f} → 送出 {sum(r['cer_sent'] for r in rs)/len(rs):.3f}")
    print("== TTS 念日韓（轉回文字的 CER，越低越好）")
    for p in ("gemini", "edge-default", "edge-native", "indextts", "voxcpm", "cosyvoice"):
        for lang in ("ja", "ko", "zh"):
            rs = [r for r in out["tts"] if r["provider"] == p and r["lang"] == lang]
            if rs:
                ok = [r["cer"] for r in rs if "cer" in r]
                print(f"  {p:12} {lang} {('%.2f' % (sum(ok)/len(ok))) if ok else '-'} ({len(rs)-len(ok)} 失敗)")

asyncio.run(main())
