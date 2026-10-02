"""Simulate avatar voice turns end to end: send audio instead of a person speaking.

走前台同一組公開端點，不繞進程式內部：

1. 語音：用系統自己的 TTS（``/v1/audio/speech``）把題目念出來，或讀真人錄音。
2. 辨識：串流（``/api/v1/asr/stream``，每 0.1 秒送 3200 bytes，跟前台一樣）與
   批次（``/api/v1/asr/transcribe``，前台 VAD 切好上傳的 wav）。
3. 回答：把辨識結果送 ``/api/v1/chat``。
4. 念出來（選用）：``/api/v1/tts/stream``，量第一段聲音多久出來。

每一題記辨識錯字率、專有名詞有沒有聽對、回答有沒有講到預期的字、各段耗時。
結束時刪掉這次建立的對話，不留在專案的對話紀錄裡。用法見同目錄 README.md。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import ssl
import subprocess
import sys
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
import websockets

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE_DIR = HERE / ".cache"
RESULTS_DIR = HERE / "results"

SAMPLE_RATE = 16000
# 前台送法：100 ms 一包（1600 個 16-bit 取樣）。
CHUNK_BYTES = 3200
CHUNK_SECONDS = 0.1
LEAD_SILENCE_CHUNKS = 3
# Gemini 停頓約 0.5 秒才定稿；多送一點靜音再送 end，像人講完停下來。
TAIL_SILENCE_CHUNKS = 15
# 前台送 end 之後最多等 5 秒收最後的定稿。
FINAL_GRACE_SECONDS = 5.0
READY_TIMEOUT_SECONDS = 10.0

_MINT_TOKEN = """
import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "/app")
from app.auth.runtime import get_auth_runtime
runtime = get_auth_runtime()
user = runtime.users.get_by_username(sys.argv[1])
if user is None:
    sys.exit(f"no such account: {sys.argv[1]}")
now = datetime.now(timezone.utc)
print(runtime.tokens.issue(user, now=now, expires_at=now + timedelta(minutes=int(sys.argv[2]))))
"""


@dataclass
class Case:
    id: str
    text: str
    terms: list[str] = field(default_factory=list)
    reply_any: list[str] = field(default_factory=list)
    audio: str = ""
    # 批次辨識該判成什麼語言："nan" 是台語，"zh" 是不該被判成台語。
    speech_language: str = ""


# 異體字不算聽錯：Breeze 常寫「汙水泵」、Gemini 寫「臺」。
_VARIANTS = str.maketrans({"汙": "污", "臺": "台", "裏": "裡", "着": "著"})


def normalize(text: str) -> str:
    """Compare what was said, not how it was written: NFKC, variants, lowercase, letters and digits only."""
    text = unicodedata.normalize("NFKC", text).lower().translate(_VARIANTS)
    return "".join(ch for ch in text if ch.isalnum())


def cer(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize(reference), normalize(hypothesis)
    previous = list(range(len(hyp) + 1))
    for i, ref_char in enumerate(ref, 1):
        current = [i]
        for j, hyp_char in enumerate(hyp, 1):
            current.append(min(
                previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref_char != hyp_char),
            ))
        previous = current
    return previous[-1] / max(len(ref), 1)


def terms_heard(terms: list[str], transcript: str) -> list[str]:
    """The expected proper nouns that came through; ``A|B`` accepts either spelling."""
    heard = normalize(transcript)
    return [term for term in terms if any(normalize(alt) in heard for alt in term.split("|"))]


def wav_bytes(pcm: bytes) -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)
    return buffer.getvalue()


def to_pcm(audio: bytes, noise: float) -> bytes:
    """Any container → 16 kHz mono PCM16; ``noise`` mixes in pink noise at that amplitude."""
    command = ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", "pipe:0"]
    if noise > 0:
        command += [
            "-f", "lavfi", "-i", f"anoisesrc=c=pink:a={noise}:r={SAMPLE_RATE}",
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:normalize=0",
        ]
    command += ["-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"]
    return subprocess.run(command, input=audio, capture_output=True, check=True).stdout


def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        if row.get("error"):
            continue
        for path in ("stream", "batch"):
            if path in row:
                groups.setdefault((row["voice"], path), []).append(row)
    summary = []
    for (voice, path), members in sorted(groups.items()):
        pairs = [(m, m[path]) for m in members if "error" not in m[path]]
        asr = [a for _, a in pairs]
        with_terms = [a for m, a in pairs if m["terms"]]
        replies = [a["reply_ok"] for a in asr if a.get("reply_ok") is not None]
        languages = [a["language_ok"] for a in asr if a.get("language_ok") is not None]
        checks = [a["language_check"] for a in asr if a.get("language_check")]

        def mean(values: list[float]) -> float | None:
            return round(sum(values) / len(values), 3) if values else None

        summary.append({
            "voice": voice,
            "path": path,
            "cases": len(members),
            "failed": len(members) - len(asr),
            "mean_cer": mean([a["cer"] for a in asr]),
            "terms_ok": f"{sum(a['terms_ok'] for a in with_terms)}/{len(with_terms)}",
            "reply_ok": f"{sum(replies)}/{len(replies)}" if replies else "-",
            "language_ok": f"{sum(languages)}/{len(languages)}" if languages else "-",
            "check_timeouts": (f"{sum(c['result'] == 'timeout' for c in checks)}/{len(checks)}"
                               if checks else "-"),
            "check_ms": mean([c["ms"] for c in checks]),
            "asr_ms": mean([a["asr_ms"] for a in asr if a.get("asr_ms") is not None]),
            "chat_ms": mean([a["chat_ms"] for a in asr if a.get("chat_ms") is not None]),
        })
    return summary


class Harness:
    def __init__(self, args: argparse.Namespace, token: str) -> None:
        self.args = args
        self.base = args.base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        self.http = httpx.AsyncClient(verify=args.verify_tls, timeout=120, headers=self.headers)
        self.ws_ssl = ssl.create_default_context()
        if not args.verify_tls:
            self.ws_ssl.check_hostname = False
            self.ws_ssl.verify_mode = ssl.CERT_NONE
        self.sessions: list[str] = []
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    def _routes(self) -> dict[str, str]:
        fields = {"project_id": self.args.project}
        if self.args.routes:
            fields["language_routes"] = self.args.routes
        return fields

    async def speech(self, case: Case, voice: str) -> bytes:
        if case.audio:
            source = (ROOT / case.audio) if not Path(case.audio).is_absolute() else Path(case.audio)
            return to_pcm(source.read_bytes(), self.args.noise)
        provider, _, voice_id = voice.partition(":")
        key = hashlib.sha256(f"{provider}|{voice_id}|{case.text}".encode()).hexdigest()[:24]
        cached = CACHE_DIR / f"{key}.audio"
        if not cached.exists():
            response = await self.http.post(
                f"{self.base}/v1/audio/speech",
                json={"input": case.text, "provider": provider, "voice": voice_id},
            )
            response.raise_for_status()
            CACHE_DIR.mkdir(exist_ok=True)
            cached.write_bytes(response.content)
        return to_pcm(cached.read_bytes(), self.args.noise)

    async def stream_asr(self, pcm: bytes) -> dict:
        query = "&".join(f"{k}={v}" for k, v in self._routes().items())
        url = self.base.replace("http", "ws", 1) + f"/api/v1/asr/stream?{query}"
        interims: list[str] = []
        finals: list[str] = []
        timeline = {"first_final": None, "last_message": time.monotonic()}
        async with websockets.connect(
            url, additional_headers=self.headers,
            ssl=self.ws_ssl if url.startswith("wss") else None,
        ) as ws:
            ready = json.loads(await asyncio.wait_for(ws.recv(), READY_TIMEOUT_SECONDS))
            if ready.get("type") != "ready":
                return {"error": f"not ready: {ready}"}

            async def reader() -> None:
                async for raw in ws:
                    message = json.loads(raw)
                    timeline["last_message"] = time.monotonic()
                    if message.get("type") == "interim":
                        interims.append(message.get("text", ""))
                    elif message.get("type") == "final":
                        finals.append(message.get("text", "").strip())
                        timeline["first_final"] = timeline["first_final"] or time.monotonic()
                    elif message.get("type") == "error":
                        finals.append(f"<error:{message.get('code')}>")

            task = asyncio.create_task(reader())
            silence = b"\0" * CHUNK_BYTES
            body = [pcm[i:i + CHUNK_BYTES] for i in range(0, len(pcm), CHUNK_BYTES)]
            for chunk in [silence] * LEAD_SILENCE_CHUNKS + body:
                await ws.send(chunk)
                await asyncio.sleep(CHUNK_SECONDS)
            speech_ended = time.monotonic()
            for _ in range(TAIL_SILENCE_CHUNKS):
                await ws.send(silence)
                await asyncio.sleep(CHUNK_SECONDS)
            await ws.send(json.dumps({"type": "end"}))
            deadline = time.monotonic() + FINAL_GRACE_SECONDS
            while time.monotonic() < deadline and not task.done():
                # 有定稿後再靜 1 秒才收：同一句可能被切成兩段定稿，前台會當兩輪送出。
                if finals and time.monotonic() - timeline["last_message"] > 1.0:
                    break
                await asyncio.sleep(0.1)
            task.cancel()
        first_final = timeline["first_final"]
        return {
            "text": " ".join(f for f in finals if f),
            "finals": finals,
            "last_interim": interims[-1] if interims else "",
            # 講完最後一個字到第一段定稿（含 Gemini 判斷停頓與 Jev 挑選），使用者在等的時間。
            "asr_ms": round((first_final - speech_ended) * 1000) if first_final else None,
        }

    async def batch_asr(self, pcm: bytes) -> dict:
        started = time.monotonic()
        response = await self.http.post(
            f"{self.base}/api/v1/asr/transcribe",
            files={"file": ("speech.wav", wav_bytes(pcm), "audio/wav")},
            data=self._routes(),
        )
        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}
        body = response.json()
        return {
            "text": body.get("text", ""),
            "provider": body.get("provider"),
            "language": body.get("language"),
            "routes": body.get("language_routes"),
            # 台語分流時才有：{"result": 語言代碼|"timeout"|"failed", "ms": ...}
            "language_check": body.get("language_check"),
            "asr_ms": round((time.monotonic() - started) * 1000),
        }

    async def chat(self, text: str, speech_language: str | None) -> dict:
        session_id = f"voice-e2e-{self.run_id}-{uuid.uuid4().hex[:8]}"
        self.sessions.append(session_id)
        payload = {
            "message": text, "project_id": self.args.project, "persona_id": "default",
            "session_id": session_id, "mode": self.args.mode,
        }
        if speech_language:
            payload["metadata"] = {"speech_language": speech_language}
        started = time.monotonic()
        response = await self.http.post(f"{self.base}/api/v1/chat", json=payload)
        chat_ms = round((time.monotonic() - started) * 1000)
        if response.status_code != 200:
            return {"chat_ms": chat_ms, "reply": "", "chat_error": f"HTTP {response.status_code}"}
        return {"chat_ms": chat_ms, "reply": response.json().get("reply", "")}

    async def tts(self, reply: str, speech_language: str | None) -> dict:
        started = time.monotonic()
        first_audio_ms = None
        size = 0
        payload = {"text": reply, "project_id": self.args.project, "speech_language": speech_language or ""}
        if self.args.tts_voice:
            payload["provider"], _, payload["voice"] = self.args.tts_voice.partition(":")
        audio = bytearray()
        async with self.http.stream("POST", f"{self.base}/api/v1/tts/stream", json=payload) as response:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                audio.extend(chunk)
                if first_audio_ms is None and size > 44:  # 44 bytes 是 wav 標頭
                    first_audio_ms = round((time.monotonic() - started) * 1000)
            return {
                "tts_status": response.status_code,
                # 串流路徑不回 X-TTS-Provider；沒帶就是帳號設定的聲音。
                "tts_provider": (response.headers.get("X-TTS-Provider")
                                 or payload.get("provider") or "account-default"),
                "tts_fallback": response.headers.get("X-TTS-Fallback"),
                "tts_first_audio_ms": first_audio_ms,
                "tts_seconds": audio_seconds(bytes(audio), response.headers.get("content-type", "")),
            }

    async def turn(self, case: Case, path: str, pcm: bytes) -> dict:
        try:
            asr = await (self.stream_asr(pcm) if path == "stream" else self.batch_asr(pcm))
        except Exception as exc:  # noqa: BLE001 - 一題壞掉照樣跑完其他題
            return {"error": f"{type(exc).__name__}: {exc}"}
        if "error" in asr:
            return asr
        asr["cer"] = round(cer(case.text, asr["text"]), 3)
        asr["terms_heard"] = terms_heard(case.terms, asr["text"])
        asr["terms_ok"] = len(asr["terms_heard"]) == len(case.terms)
        if case.speech_language and path == "batch":
            # 串流不判台語（台語分流時前台不走串流），只有批次回 language。
            asr["language_ok"] = (asr.get("language") == "nan") == (case.speech_language == "nan")
        steps = self.args.steps
        speech_language = asr.get("language") if asr.get("language") == "nan" else None
        if "chat" in steps and asr["text"]:
            asr.update(await self.chat(asr["text"], speech_language))
            if case.reply_any:
                asr["reply_ok"] = bool(terms_heard(["|".join(case.reply_any)], asr["reply"]))
            if "tts" in steps and asr.get("reply"):
                try:
                    asr.update(await self.tts(asr["reply"], speech_language))
                except Exception as exc:  # noqa: BLE001
                    asr["tts_error"] = f"{type(exc).__name__}: {exc}"
        return asr

    async def run_case(self, case: Case, voice: str, gate: asyncio.Semaphore) -> dict:
        async with gate:
            row: dict = {"id": case.id, "voice": "recording" if case.audio else voice,
                         "ref": case.text, "terms": case.terms}
            try:
                pcm = await self.speech(case, voice)
            except Exception as exc:  # noqa: BLE001
                row["error"] = f"speech: {type(exc).__name__}: {exc}"
                print(f"  ✗ {case.id} [{voice}] {row['error']}", flush=True)
                return row
            for path in self.args.asr:
                row[path] = await self.turn(case, path, pcm)
                result = row[path]
                if "error" in result:
                    print(f"  ✗ {case.id} [{row['voice']}] {path}: {result['error']}", flush=True)
                    continue
                mark = "✓" if result["terms_ok"] and result.get("language_ok", True) else "✗"
                reply = result.get("reply", "")[:40].replace("\n", " ")
                language = f" lang={result.get('language') or '-'}" if case.speech_language else ""
                print(f"  {mark} {case.id} [{row['voice']}] {path} cer={result['cer']:.2f}{language} "
                      f"heard={result['text']!r} reply={reply!r}", flush=True)
            return row

    async def cleanup(self) -> None:
        if not self.sessions or self.args.keep_sessions:
            return
        response = await self.http.post(
            f"{self.base}/api/v1/sessions/batch-delete",
            params={"project_id": self.args.project},
            json={"session_ids": self.sessions},
        )
        if response.status_code != 200:
            print(f"清理對話失敗 HTTP {response.status_code}；session 前綴 voice-e2e-{self.run_id}", file=sys.stderr)


def audio_seconds(audio: bytes, content_type: str) -> float:
    """How long the reply is spoken: Edge streams mp3, VoxCPM wav, Gemini raw PCM."""
    if not audio:
        return 0.0
    if "pcm" in content_type or "L16" in content_type:
        rate = int(re.search(r"rate=(\d+)", content_type).group(1)) if "rate=" in content_type else SAMPLE_RATE
        return round(len(audio) / (rate * 2), 1)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", "-i", "pipe:0"],
        input=audio, capture_output=True,
    )
    try:
        return round(float(probe.stdout.strip()), 1)
    except ValueError:
        # 串流 mp3 沒有長度標頭時 ffprobe 讀不到，改用解碼後的取樣數。
        decoded = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(SAMPLE_RATE),
             "-f", "s16le", "pipe:1"],
            input=audio, capture_output=True,
        ).stdout
        return round(len(decoded) / (SAMPLE_RATE * 2), 1)


def mint_token(username: str, minutes: int) -> str:
    """Sign a short-lived session token inside the backend container: no password on disk."""
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "backend", "python3", "-", username, str(minutes)],
        input=_MINT_TOKEN, capture_output=True, text=True, cwd=ROOT,
    )
    if result.returncode != 0:
        sys.exit(f"無法簽 token：{result.stderr.strip()[-300:]}")
    return result.stdout.strip().splitlines()[-1]


def load_cases(path: Path, only: list[str]) -> tuple[list[Case], dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = [Case(**item) for item in data["cases"]]
    if only:
        cases = [case for case in cases if any(re.search(pattern, case.id) for pattern in only)]
    return cases, data


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cases", type=Path, help="題庫 JSON（見 cases/）")
    parser.add_argument("--user", help="用這個帳號跑（在 backend 容器裡簽 token）")
    parser.add_argument("--token", help="直接給 Bearer token，不簽")
    parser.add_argument("--base-url", default="https://localhost:8787")
    # 本機 nginx 掛的是正式網域的憑證，打 localhost 驗不過；打正式網域時再開。
    parser.add_argument("--verify-tls", action="store_true", help="驗 TLS 憑證")
    parser.add_argument("--project", help="專案 ID；預設用題庫的 project_id")
    parser.add_argument("--routes", default="", help="語言分流，例如 zh,en；預設用後台設定")
    parser.add_argument("--asr", type=lambda s: s.split(","),
                        help="stream、batch 或兩個都跑；預設用題庫的 asr，沒寫就兩個都跑")
    parser.add_argument("--steps", default="chat", type=lambda s: set(s.split(",")) - {""},
                        help="辨識後還要做的：chat、tts（逗號分隔；空字串只測辨識）")
    parser.add_argument("--voices", type=lambda s: s.split(","),
                        help="provider:voice 逗號分隔；預設用題庫的 voices")
    parser.add_argument("--only", nargs="*", default=[], help="只跑 id 符合這些 regex 的題目")
    parser.add_argument("--noise", type=float, default=0.0, help="混入粉紅雜訊的振幅，例如 0.02")
    parser.add_argument("--mode", default="fast", help="回覆深度：fast、standard、deep")
    parser.add_argument("--tts-voice", default="", help="念回答用的 provider:voice；預設用帳號設定")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--keep-sessions", action="store_true", help="不刪這次建立的對話")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases, data = load_cases(args.cases, args.only)
    args.project = args.project or data.get("project_id", "default")
    voices = args.voices or data.get("voices", ["edge-tts:zh-TW-HsiaoChenNeural"])
    args.asr = args.asr or data.get("asr", ["stream", "batch"])
    if not args.token and not args.user:
        sys.exit("要給 --user（簽 token）或 --token")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.project_mirror import MIRRORS, check as mirror_matches

    # 測試專案跟正式專案不一樣時，量出來的數字不能代表正式環境。
    if args.project in MIRRORS and not mirror_matches(args.project):
        sys.exit(1)
    token = args.token or mint_token(args.user, 60)
    harness = Harness(args, token)
    gate = asyncio.Semaphore(args.concurrency)
    jobs = [harness.run_case(case, voice, gate)
            for case in cases for voice in ([voices[0]] if case.audio else voices)]
    print(f"{len(jobs)} 輪（{len(cases)} 題 × 聲音），專案 {args.project}，辨識 {','.join(args.asr)}，"
          f"之後 {','.join(sorted(args.steps)) or '不問 Brain'}", flush=True)
    try:
        rows = await asyncio.gather(*jobs)
    finally:
        await harness.cleanup()
        await harness.http.aclose()
    summary = summarize(rows)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{args.cases.stem}-{harness.run_id}.json"
    out.write_text(json.dumps({"args": {k: sorted(v) if isinstance(v, set) else str(v) if isinstance(v, Path) else v
                                        for k, v in vars(args).items() if k != "token"},
                               "summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print("\n聲音 × 辨識路徑          題數 失敗 平均錯字率 專有名詞 語言判斷 判斷逾時 判斷ms 回答命中 辨識ms  回答ms")
    for s in summary:
        print(f"{s['voice'][:22]:22} {s['path']:6} {s['cases']:4} {s['failed']:4} "
              f"{s['mean_cer'] if s['mean_cer'] is not None else '-':>9} {s['terms_ok']:>8} "
              f"{s['language_ok']:>8} {s['check_timeouts']:>8} {s['check_ms'] or '-':>6} "
              f"{s['reply_ok']:>8} {s['asr_ms'] or '-':>7} {s['chat_ms'] or '-':>7}")
    print(f"\n逐題結果：{out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
