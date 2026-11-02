"""Transcribe one whole clip through one Gemini Live session.

整段音訊一次送完（不照實際時間慢慢送），關掉伺服器 VAD，用 activityStart／activityEnd
框住整段，所以一定只算一段話。每個請求開一條新 session：沿用或預熱只省連線與 setup 約
0.26 秒，但閒置的 session 50–60 秒就被斷線，每條待命連線每小時要重連約 80 次，不值得。

判定收完（實測 2026-10-30）：

- 有講話：定稿 inputTranscription → generationComplete → ACTIVITY_END。收到
  generationComplete 就結束。
- 靜音或雜訊：沒有定稿，也沒有 generationComplete，只有 ACTIVITY_END。再等一小段確認
  沒有定稿跟在後面，回空字串。
- 上游一直不回：這裡不另外計時，由 transcribe() 的單站預算取消，連線跟著關掉。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import httpx
import websockets

from app.gateway import gemini_transcription as gemini

# 開頭沒留白時 Live 會聽錯（「hours in the morning」變「in Timmins」）。前導 0.1、0.3、
# 0.5 秒全對，0.2 秒反而錯一句，取 0.3 留餘裕；有 activityEnd 收尾，後面不必補靜音。
_LEAD_SILENCE_SECONDS = 0.3
_CHUNK_BYTES = 3200  # 100 ms
_SETTLE_SECONDS = 0.5
_MAX_MESSAGE_BYTES = 4 * 1024 * 1024
# Live 用關閉碼回報伺服器端失敗；換算成 5xx，斷路器才會把它算進連續失敗。
_SERVER_SIDE_CLOSE_CODES = frozenset({1011, 1012, 1013})
_CJK = re.compile(r"[　-鿿＀-￯]")


class GeminiLiveBatchError(RuntimeError):
    """Gemini refused or dropped the session; ``status_code`` feeds the breaker."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class LiveBatchResult:
    text: str
    finals: tuple[str, ...]
    # generation_complete、activity_end（靜音）、closed：用哪個訊號判定收完。
    completed_by: str


def _join_finals(finals: list[str]) -> str:
    joined = ""
    for text in finals:
        if joined and not (_CJK.match(joined[-1]) and _CJK.match(text[0])):
            joined += " "
        joined += text
    return joined


async def _collect_finals(upstream) -> tuple[list[str], str]:
    finals: list[str] = []
    activity_ended = False
    while True:
        try:
            raw = await asyncio.wait_for(
                upstream.recv(), _SETTLE_SECONDS if activity_ended else None,
            )
        except TimeoutError:
            return finals, "activity_end"
        except websockets.ConnectionClosed:
            # 定稿已經到手：斷線不影響結果；還沒拿到才算失敗，交給外層分類。
            if finals:
                return finals, "closed"
            raise
        event = gemini.parse_live_message(raw)
        if text := event.final.strip():
            finals.append(text)
        if event.generation_complete:
            return finals, "generation_complete"
        if event.voice_activity == "ACTIVITY_END":
            activity_ended = True


async def transcribe_pcm(
    pcm: bytes, *,
    api_key: str,
    transcription: dict,
    connect_timeout: float,
) -> LiveBatchResult:
    """Send 16 kHz mono PCM16 through a fresh session and return its joined finals."""
    padded = b"\0\0" * int(gemini.SAMPLE_RATE * _LEAD_SILENCE_SECONDS) + pcm
    try:
        async with websockets.connect(
            gemini.GEMINI_LIVE_URL,
            additional_headers={"x-goog-api-key": api_key},
            max_size=_MAX_MESSAGE_BYTES,
            open_timeout=connect_timeout,
        ) as upstream:
            await upstream.send(gemini.setup_message(transcription, manual_activity=True))
            if not gemini.parse_setup_reply(await upstream.recv()):
                raise GeminiLiveBatchError("Gemini Live setup rejected")
            await upstream.send(gemini.ACTIVITY_START)
            for start in range(0, len(padded), _CHUNK_BYTES):
                await upstream.send(gemini.audio_message(padded[start:start + _CHUNK_BYTES]))
            await upstream.send(gemini.ACTIVITY_END)
            finals, completed_by = await _collect_finals(upstream)
    # 下面全部 from None：握手請求帶著金鑰，不把它掛在例外鏈上。
    except TimeoutError:
        raise httpx.ConnectTimeout("Gemini Live connect timed out") from None
    except websockets.InvalidStatus as exc:
        status = exc.response.status_code
        raise GeminiLiveBatchError(f"Gemini Live rejected the connection (HTTP {status})", status) from None
    except websockets.ConnectionClosed as exc:
        code = exc.rcvd.code if exc.rcvd is not None else 1006
        raise GeminiLiveBatchError(
            f"Gemini Live closed before a transcript (code {code})",
            503 if code in _SERVER_SIDE_CLOSE_CODES else 0,
        ) from None
    except OSError as exc:
        raise httpx.ConnectError(f"Gemini Live unreachable ({type(exc).__name__})") from None
    return LiveBatchResult(_join_finals(finals), tuple(finals), completed_by)
