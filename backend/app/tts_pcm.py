"""Streaming conversion of any TTS engine output to 16 kHz mono s16le raw PCM.

`POST /api/v1/tts/stream` 預設照引擎原樣回傳（Gemini raw PCM 24k、VoxCPM／
IndexTTS WAV、Edge／CosyVoice MP3）。帶 ``format=pcm16k`` 時改走這裡，讓
MatesX 之類只吃 16 kHz raw PCM 的對嘴引擎不必自己處理各家格式。

三條轉換路徑，依「先看內容、再看 Content-Type」判斷：

* 開頭是 ``RIFF``／``RF64`` … ``WAVE`` → 在程序內解析 WAV（不假設 data 在第
  44 byte，也接受串流 WAV 未知長度）。
* ``audio/l16``／``audio/pcm`` → 視為 16-bit little-endian raw PCM（本服務各
  adapter 的契約；RFC 2586 的 L16 是 big-endian，但上游實際送 LE）。
* 其餘（MP3 等）→ 串流餵給 ffmpeg 子程序解碼。

前兩條的重採樣用純 Python 的有狀態 polyphase FIR，濾波器歷史與相位跨 chunk
保留，所以 chunk 邊界不會有爆音；不引入 numpy 等新相依。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import shutil
import sys
from array import array
from collections.abc import AsyncIterator, Sequence
from operator import mul

logger = logging.getLogger("backend.tts_pcm")

PCM16K_FORMAT = "pcm16k"
PCM16K_RATE = 16000
PCM16K_CONTENT_TYPE = "audio/l16;rate=16000;channels=1"

_BIG_ENDIAN = sys.byteorder == "big"
_FFMPEG_READ_SIZE = 8192
BUFFERED_CHUNK_SIZE = 8192

_WAVE_FORMAT_PCM = 0x0001
_WAVE_FORMAT_IEEE_FLOAT = 0x0003
_WAVE_FORMAT_EXTENSIBLE = 0xFFFE


def _bessel_i0(x: float) -> float:
    total = term = 1.0
    k = 1
    half = x / 2.0
    while term > 1e-12 * total:
        term *= (half / k) ** 2
        total += term
        k += 1
    return total


def _clip_pack(values: Sequence[float]) -> bytes:
    out = array("h", [
        32767 if v >= 32766.5 else -32768 if v <= -32767.5 else round(v)
        for v in values
    ])
    if _BIG_ENDIAN:
        out.byteswap()
    return out.tobytes()


def _pack_ints(values: Sequence[int]) -> bytes:
    out = values if isinstance(values, array) else array("h", values)
    if _BIG_ENDIAN:
        out = array("h", out)
        out.byteswap()
    return out.tobytes()


class StreamingResampler:
    """Rational polyphase FIR resampler for mono int16 samples.

    Keeps the input history and the output phase between ``process`` calls, so
    feeding a signal in arbitrary pieces yields exactly the same samples as
    feeding it at once. Output is delay-compensated: sample ``j`` lines up with
    input time ``j / out_rate``; ``flush`` emits the tail held back for the
    filter's look-ahead (half the filter length, ~0.5 ms at 24 kHz).
    """

    def __init__(self, in_rate: int, out_rate: int = PCM16K_RATE) -> None:
        if in_rate <= 0 or out_rate <= 0:
            raise ValueError("sample rates must be positive")
        g = math.gcd(in_rate, out_rate)
        self._up = up = out_rate // g
        self._down = down = in_rate // g
        # 降採樣比越大，濾波器在輸入端要越長才壓得住混疊；24k→16k 為 24 taps。
        self._taps = taps = max(16, math.ceil(16 * down / up))
        length = taps * up
        cutoff = 0.5 / max(up, down) * 0.9
        beta = 8.0
        # 濾波器中心對齊整數延遲，輸出才不會偏半個樣本（1 kHz 會差到 6%）。
        centre = float((length - 1) // 2)
        i0_beta = _bessel_i0(beta)
        proto = []
        for i in range(length):
            x = i - centre
            sinc = 2 * cutoff * (
                1.0 if x == 0 else math.sin(2 * math.pi * cutoff * x) / (2 * math.pi * cutoff * x)
            )
            r = 2.0 * i / (length - 1) - 1.0 if length > 1 else 0.0
            window = _bessel_i0(beta * math.sqrt(max(0.0, 1.0 - r * r))) / i0_beta
            proto.append(sinc * window * up)
        # phases[p] 依輸入由舊到新排列，可以直接和 buffer 切片做內積。
        self._phases = [
            [proto[p + k * up] for k in reversed(range(taps))] for p in range(up)
        ]
        self._delay = (length - 1) // 2
        self._buf: list[int] = [0] * (taps - 1)
        self._buf_start = -(taps - 1)
        self._n_in = 0
        self._j = 0
        self._flushed = False

    def _run(self, last_index: int, limit: int | None) -> list[float]:
        up, down, delay, taps = self._up, self._down, self._delay, self._taps
        phases, buf, start = self._phases, self._buf, self._buf_start
        out: list[float] = []
        append = out.append
        j = self._j
        while limit is None or j < limit:
            t = j * down + delay
            n_hi = t // up
            if n_hi > last_index:
                break
            s = n_hi - taps + 1 - start
            append(sum(map(mul, phases[t % up], buf[s:s + taps])))
            j += 1
        self._j = j
        keep_from = (j * down + delay) // up - taps + 1
        drop = keep_from - start
        if drop > 0:
            del buf[:drop]
            self._buf_start = keep_from
        return out

    def process(self, samples: Sequence[int]) -> bytes:
        if self._flushed:
            raise RuntimeError("resampler already flushed")
        if not samples:
            return b""
        self._buf.extend(samples)
        self._n_in += len(samples)
        return _clip_pack(self._run(self._n_in - 1, None))

    def flush(self) -> bytes:
        if self._flushed:
            return b""
        self._flushed = True
        total = (self._n_in * self._up + self._down - 1) // self._down
        if self._j >= total:
            return b""
        need = ((total - 1) * self._down + self._delay) // self._up
        pad = need - (self._buf_start + len(self._buf) - 1)
        if pad > 0:
            self._buf.extend([0] * pad)
        return _clip_pack(self._run(need, total))


class PcmToPcm16k:
    """Interleaved PCM of any common layout → 16 kHz mono s16le, incrementally.

    Holds back a partial frame (e.g. half a sample) until the next chunk.
    """

    def __init__(
        self,
        *,
        rate: int,
        channels: int = 1,
        bits: int = 16,
        float_samples: bool = False,
    ) -> None:
        if channels < 1:
            raise ValueError("channels must be >= 1")
        supported = (32, 64) if float_samples else (8, 16, 24, 32)
        if bits not in supported:
            raise ValueError(f"unsupported sample format: {bits}-bit {'float' if float_samples else 'int'}")
        self._channels = channels
        self._bits = bits
        self._float = float_samples
        self._frame = channels * bits // 8
        self._rest = b""
        self._resampler = None if rate == PCM16K_RATE else StreamingResampler(rate)
        self._passthrough = rate == PCM16K_RATE and channels == 1 and bits == 16 and not float_samples

    def _to_mono(self, data: bytes) -> Sequence[int]:
        bits = self._bits
        if self._float:
            values = array("f" if bits == 32 else "d")
            values.frombytes(data)
            if _BIG_ENDIAN:
                values.byteswap()
            samples: Sequence[int] = [
                32767 if v >= 1.0 else -32768 if v <= -1.0 else int(v * 32767.0)
                for v in values
            ]
        elif bits == 8:
            samples = [(b - 128) << 8 for b in data]
        else:
            if bits == 16:
                raw = data
            else:
                # 24／32-bit 只取高 16 位：以擴充切片把每個樣本的最高兩 byte 搬出來。
                width = bits // 8
                raw = bytearray(len(data) // width * 2)
                raw[0::2] = data[width - 2::width]
                raw[1::2] = data[width - 1::width]
            samples = array("h")
            samples.frombytes(bytes(raw))
            if _BIG_ENDIAN:
                samples.byteswap()
        ch = self._channels
        if ch == 1:
            return samples
        if ch == 2:
            return [(a + b) >> 1 for a, b in zip(samples[0::2], samples[1::2])]
        return [sum(frame) // ch for frame in zip(*(samples[c::ch] for c in range(ch)))]

    def feed(self, data: bytes) -> bytes:
        if not data:
            return b""
        if self._rest:
            data = self._rest + data
        usable = len(data) - len(data) % self._frame
        self._rest = data[usable:]
        if not usable:
            return b""
        chunk = data[:usable]
        if self._passthrough:
            return bytes(chunk)
        mono = self._to_mono(chunk)
        if self._resampler is None:
            return _pack_ints(mono)
        return self._resampler.process(mono)

    def finish(self) -> bytes:
        # 結尾不足一個 frame 的殘餘 byte 無法還原成樣本，直接丟掉。
        self._rest = b""
        return self._resampler.flush() if self._resampler is not None else b""


class UnsupportedWav(Exception):
    """WAV the in-process path cannot decode; ``prefix`` holds every byte read so far."""

    def __init__(self, reason: str, prefix: bytes) -> None:
        super().__init__(reason)
        self.prefix = prefix


def _plausible_chunk_id(chunk_id: bytes) -> bool:
    return all(32 <= b < 127 for b in chunk_id)


class WavStreamParser:
    """Incremental RIFF/WAVE parser that emits 16 kHz mono s16le.

    Walks chunks instead of assuming a 44-byte header, so ``LIST``/``fact``
    chunks before ``data`` are skipped. A ``data`` size of 0, 0xFFFFFFFF or
    near 2 GiB marks a streamed WAV whose length was unknown when the header
    was written; it is read to end of stream. A declared size that turns out to
    be too small (bytes after it do not look like a chunk header) is also
    treated as streamed rather than truncating the audio.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._prefix = bytearray()
        self._state = "riff"
        self._remaining: int | None = None
        self._skip = 0
        self._data_pad = 0
        self._converter: PcmToPcm16k | None = None
        self._done = False
        self._entered_data = False

    def _fail(self, reason: str) -> UnsupportedWav:
        return UnsupportedWav(reason, bytes(self._prefix) + bytes(self._buf))

    def _parse_fmt(self, body: bytes) -> None:
        if len(body) < 16:
            raise self._fail("fmt chunk too short")
        tag = int.from_bytes(body[0:2], "little")
        channels = int.from_bytes(body[2:4], "little")
        rate = int.from_bytes(body[4:8], "little")
        bits = int.from_bytes(body[14:16], "little")
        if tag == _WAVE_FORMAT_EXTENSIBLE and len(body) >= 26:
            tag = int.from_bytes(body[24:26], "little")
        if tag not in (_WAVE_FORMAT_PCM, _WAVE_FORMAT_IEEE_FLOAT):
            raise self._fail(f"wav format tag 0x{tag:04x} not handled in-process")
        try:
            self._converter = PcmToPcm16k(
                rate=rate,
                channels=channels,
                bits=bits,
                float_samples=tag == _WAVE_FORMAT_IEEE_FLOAT,
            )
        except ValueError as exc:
            raise self._fail(str(exc)) from exc

    def feed(self, data: bytes) -> bytes:
        if self._done or not data:
            return b""
        if self._state == "data" and self._remaining is None:
            assert self._converter is not None
            return self._converter.feed(data)
        self._buf += data
        out = bytearray()
        while True:
            buf = self._buf
            if self._state == "riff":
                if len(buf) < 12:
                    break
                if buf[0:4] not in (b"RIFF", b"RF64") or buf[8:12] != b"WAVE":
                    raise self._fail("not a RIFF/WAVE stream")
                self._consume_header(12)
                self._state = "chunk"
            elif self._state == "skip":
                take = min(self._skip, len(buf))
                self._consume_header(take)
                self._skip -= take
                if self._skip:
                    break
                self._state = "chunk"
            elif self._state == "chunk":
                if len(buf) < 8:
                    break
                chunk_id = bytes(buf[0:4])
                size = int.from_bytes(buf[4:8], "little")
                if self._entered_data and not _plausible_chunk_id(chunk_id):
                    # data 的宣告長度比實際短（串流時先寫的估計值）：剩下的仍是音訊。
                    self._state = "data"
                    self._remaining = None
                    continue
                if chunk_id == b"fmt ":
                    if len(buf) < 8 + size:
                        break
                    self._parse_fmt(bytes(buf[8:8 + size]))
                    self._consume_header(8 + size)
                    self._skip = size & 1
                    self._state = "skip"
                elif chunk_id == b"data":
                    if self._converter is None:
                        raise self._fail("data chunk before fmt chunk")
                    self._consume_header(8)
                    streamed = size == 0 or size >= 0x7F000000
                    self._remaining = None if streamed else size
                    self._data_pad = 0 if streamed else size & 1
                    self._state = "data"
                    self._entered_data = True
                    self._prefix.clear()
                else:
                    self._consume_header(8)
                    self._skip = size + (size & 1)
                    self._state = "skip"
            else:  # data
                assert self._converter is not None
                if self._remaining is None:
                    out += self._converter.feed(bytes(buf))
                    buf.clear()
                    break
                take = min(self._remaining, len(buf))
                out += self._converter.feed(bytes(buf[:take]))
                del buf[:take]
                self._remaining -= take
                if self._remaining:
                    break
                self._skip = self._data_pad
                self._state = "skip"
        return bytes(out)

    def _consume_header(self, n: int) -> None:
        # 進入 data 前讀過的 byte 都留著，格式不支援時要整段交給 ffmpeg 重讀。
        if self._state != "data" and not self._entered_data:
            self._prefix += self._buf[:n]
        del self._buf[:n]

    def finish(self) -> bytes:
        self._done = True
        if self._converter is None:
            return b""
        return self._converter.finish()


def parse_content_type(content_type: str) -> tuple[str, dict[str, str]]:
    parts = [p.strip() for p in (content_type or "").split(";")]
    params: dict[str, str] = {}
    for part in parts[1:]:
        key, _, value = part.partition("=")
        if key:
            params[key.strip().lower()] = value.strip().strip('"')
    return parts[0].lower(), params


def _raw_pcm_layout(content_type: str) -> tuple[int, int] | None:
    mime, params = parse_content_type(content_type)
    if mime not in ("audio/l16", "audio/pcm", "audio/raw", "audio/x-raw"):
        return None
    try:
        rate = int(params.get("rate", PCM16K_RATE))
        channels = int(params.get("channels", 1))
    except ValueError:
        return None
    return rate, channels


async def iter_bytes(data: bytes, chunk_size: int = BUFFERED_CHUNK_SIZE) -> AsyncIterator[bytes]:
    """Turn a buffered engine result into chunks so conversion output streams too."""
    for i in range(0, len(data), chunk_size):
        yield data[i:i + chunk_size]


async def _aclose(source: AsyncIterator[bytes]) -> None:
    close = getattr(source, "aclose", None)
    if close is not None:
        try:
            await close()
        except Exception:  # pragma: no cover - best effort cleanup
            logger.debug("tts_pcm source close failed", exc_info=True)


def _slices(data: bytes, size: int = BUFFERED_CHUNK_SIZE):
    # 純 Python 重採樣每秒音訊約 70–100 ms CPU；大 chunk 切小塊轉，輸出早點送出，
    # 也不會一次佔住 event loop 太久。
    if len(data) <= size:
        yield data
        return
    for i in range(0, len(data), size):
        yield data[i:i + size]


async def _replay(prefix: bytes, source: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    if prefix:
        yield prefix
    async for chunk in source:
        yield chunk


async def ffmpeg_to_pcm16k(source: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Decode any container ffmpeg understands, feeding input as it arrives."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is not installed; cannot convert to pcm16k")
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
        # 預設 probesize 5 MB 會先吃很多輸入才開始解碼，拉長首包延遲。
        "-probesize", "32768", "-analyzeduration", "0",
        "-i", "pipe:0",
        "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(PCM16K_RATE),
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    stdin, stdout, stderr = proc.stdin, proc.stdout, proc.stderr

    async def _feed() -> None:
        try:
            async for chunk in source:
                if chunk:
                    stdin.write(chunk)
                    await stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            # ffmpeg 已結束（解碼失敗或被取消）；錯誤訊息由 stderr 記錄。
            return
        finally:
            with contextlib.suppress(OSError, RuntimeError):
                stdin.close()

    feeder = asyncio.create_task(_feed())
    stderr_task = asyncio.create_task(stderr.read())
    rest = b""
    try:
        while True:
            data = await stdout.read(_FFMPEG_READ_SIZE)
            if not data:
                break
            data = rest + data
            usable = len(data) & ~1
            rest = data[usable:]
            if usable:
                yield data[:usable]
        await feeder
        code = await proc.wait()
        if code != 0:
            detail = (await stderr_task).decode("utf-8", errors="replace").strip()
            logger.warning("tts_pcm ffmpeg exited %s: %s", code, detail[:500])
    finally:
        if not feeder.done():
            feeder.cancel()
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        if not stderr_task.done():
            stderr_task.cancel()
        await _aclose(source)


async def _pieces(head: bytes, iterator: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    for piece in _slices(head):
        yield piece
    async for chunk in iterator:
        for piece in _slices(chunk):
            yield piece


async def _decode_with_ffmpeg(source: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    async with contextlib.aclosing(ffmpeg_to_pcm16k(source)) as decoded:
        async for out in decoded:
            yield out


async def convert_to_pcm16k(
    source: AsyncIterator[bytes],
    content_type: str,
) -> AsyncIterator[bytes]:
    """Stream ``source`` (audio of ``content_type``) as 16 kHz mono s16le."""
    head = b""
    iterator = source.__aiter__()
    try:
        while len(head) < 12:
            try:
                head += await iterator.__anext__()
            except StopAsyncIteration:
                break
        if not head:
            return

        is_wav = head[0:4] in (b"RIFF", b"RF64") and head[8:12] == b"WAVE"
        layout = None if is_wav else _raw_pcm_layout(content_type)
        if not is_wav and layout is None:
            async for out in _decode_with_ffmpeg(_replay(head, iterator)):
                yield out
            return

        pieces = _pieces(head, iterator)
        converter: WavStreamParser | PcmToPcm16k
        if is_wav:
            converter = WavStreamParser()
        else:
            assert layout is not None
            converter = PcmToPcm16k(rate=layout[0], channels=layout[1])
        unsupported: UnsupportedWav | None = None
        async for piece in pieces:
            try:
                # 純 Python 重採樣每塊約 10–17 ms CPU；丟到執行緒算，event loop 才能同時
                # 服務其他請求與其他路串流，不會被一路 TTS 卡住。
                out = await asyncio.to_thread(converter.feed, piece)
            except UnsupportedWav as exc:
                unsupported = exc
                break
            if out:
                yield out
        if unsupported is not None:
            # 不認得的 WAV 編碼（ADPCM 等）：已讀的 byte 加上還沒讀的整段交給 ffmpeg。
            logger.info("tts_pcm wav fallback to ffmpeg: %s", unsupported)
            async for out in _decode_with_ffmpeg(_replay(unsupported.prefix, pieces)):
                yield out
            return
        tail = await asyncio.to_thread(converter.finish)
        if tail:
            yield tail
    finally:
        await _aclose(iterator)
