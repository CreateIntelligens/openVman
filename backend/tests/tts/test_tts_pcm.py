"""format=pcm16k converters: every engine's audio becomes 16 kHz mono s16le."""

from __future__ import annotations

import asyncio
import math
import shutil
import struct
import subprocess
from array import array

import pytest

from app.tts_pcm import (
    PcmToPcm16k,
    StreamingResampler,
    WavStreamParser,
    convert_to_pcm16k,
    ffmpeg_to_pcm16k,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed on this host")


def _sine(rate: int, seconds: float, freq: float = 440.0, amp: int = 10000) -> list[int]:
    return [int(amp * math.sin(2 * math.pi * freq * n / rate)) for n in range(int(rate * seconds))]


def _s16(values: list[int]) -> bytes:
    return array("h", values).tobytes()


def _samples(data: bytes) -> array:
    out = array("h")
    out.frombytes(data)
    return out


def _wav(
    pcm: bytes,
    *,
    rate: int,
    channels: int = 1,
    bits: int = 16,
    tag: int = 1,
    data_size: int | None = None,
    extra_chunks: bytes = b"",
    trailer: bytes = b"",
) -> bytes:
    block = channels * bits // 8
    fmt = struct.pack("<HHIIHH", tag, channels, rate, rate * block, block, bits)
    size = len(pcm) if data_size is None else data_size
    body = (
        b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + extra_chunks
        + b"data" + struct.pack("<I", size) + pcm
        + trailer
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _split(data: bytes, sizes: list[int]) -> list[bytes]:
    pieces, i, k = [], 0, 0
    while i < len(data):
        n = sizes[k % len(sizes)]
        pieces.append(data[i:i + n])
        i += n
        k += 1
    return pieces


async def _agen(pieces: list[bytes]):
    for piece in pieces:
        yield piece


def _collect(pieces: list[bytes], content_type: str) -> bytes:
    async def run() -> bytes:
        out = b""
        async for chunk in convert_to_pcm16k(_agen(pieces), content_type):
            assert len(chunk) % 2 == 0, "every chunk must hold whole samples"
            out += chunk
        return out

    return asyncio.run(run())


def test_resampler_output_is_independent_of_chunking():
    signal = _sine(24000, 0.5)
    whole = StreamingResampler(24000)
    expected = whole.process(signal) + whole.flush()

    pieced = StreamingResampler(24000)
    out = b""
    i = 0
    for n in [1, 7, 333, 2, 1001, 13] * 200:
        if i >= len(signal):
            break
        out += pieced.process(signal[i:i + n])
        i += n
    out += pieced.flush()

    assert out == expected
    assert len(_samples(expected)) == 8000


def test_resampler_keeps_a_tone_in_place():
    out = StreamingResampler(24000)
    data = out.process(_sine(24000, 1.0, freq=1000)) + out.flush()
    samples = _samples(data)
    ideal = _sine(16000, 1.0, freq=1000)
    # 跳過頭尾濾波器暫態；中段誤差要遠小於振幅 10000。
    assert max(abs(a - b) for a, b in zip(samples[200:-200], ideal[200:-200])) < 100


def test_resampler_suppresses_content_above_new_nyquist():
    out = StreamingResampler(24000)
    data = out.process(_sine(24000, 0.5, freq=10000)) + out.flush()
    assert max(abs(v) for v in _samples(data)[200:-200]) < 50


def test_raw_pcm_24k_split_at_odd_byte_offsets_matches_unsplit():
    raw = _s16(_sine(24000, 0.3))
    unsplit = _collect([raw], "audio/l16;rate=24000;channels=1")
    # 奇數大小的 chunk 會把一個樣本切成兩半，轉換器要等下一塊補齊。
    split = _collect(_split(raw, [1, 3, 4097, 5, 2, 999]), "audio/l16;rate=24000;channels=1")
    assert split == unsplit
    assert len(unsplit) == 2 * 4800


def test_raw_pcm_already_16k_passes_through():
    raw = _s16(_sine(16000, 0.1))
    assert _collect(_split(raw, [3, 5]), "audio/l16;rate=16000;channels=1") == raw


def test_wav_with_data_chunk_after_other_chunks():
    pcm = _s16(_sine(16000, 0.1))
    listing = b"LIST" + struct.pack("<I", 5) + b"INFOx" + b"\x00"  # 奇數大小帶 pad byte
    wav = _wav(pcm, rate=16000, extra_chunks=listing)
    assert wav.index(b"data") + 8 != 44
    assert _collect(_split(wav, [7, 1, 50]), "audio/wav") == pcm


def test_wav_trailing_chunk_after_declared_data_is_not_audio():
    pcm = _s16(_sine(16000, 0.05))
    wav = _wav(pcm, rate=16000, trailer=b"LIST" + struct.pack("<I", 4) + b"INFO")
    assert _collect([wav], "audio/wav") == pcm


@pytest.mark.parametrize("placeholder", [0, 0xFFFFFFFF, 0x7FFFFFFF])
def test_streamed_wav_with_unknown_size_reads_to_end(placeholder):
    signal = _sine(48000, 0.2)
    wav = _wav(_s16(signal), rate=48000, data_size=placeholder)
    out = _collect(_split(wav, [44, 1, 4095, 3]), "audio/wav; rate=48000")
    ref = StreamingResampler(48000)
    assert out == ref.process(signal) + ref.flush()


def test_streamed_wav_with_too_small_size_keeps_the_rest():
    pcm = _s16(_sine(16000, 0.1))
    wav = _wav(pcm, rate=16000, data_size=200)
    assert _collect([wav], "audio/wav") == pcm


def test_stereo_wav_is_downmixed():
    left = _sine(16000, 0.05, amp=8000)
    stereo = array("h")
    for v in left:
        stereo.extend((v, v // 2))
    out = _samples(_collect([_wav(stereo.tobytes(), rate=16000, channels=2)], "audio/wav"))
    assert list(out) == [(v + v // 2) >> 1 for v in left]


def test_24bit_and_float_wav_become_16bit():
    signal = _sine(16000, 0.02)
    pcm24 = b"".join((v << 8).to_bytes(3, "little", signed=True) for v in signal)
    assert list(_samples(_collect([_wav(pcm24, rate=16000, bits=24)], "audio/wav"))) == signal

    floats = array("f", [v / 32767.0 for v in signal]).tobytes()
    out = _samples(_collect([_wav(floats, rate=16000, bits=32, tag=3)], "audio/wav"))
    assert max(abs(a - b) for a, b in zip(out, signal)) <= 1


def test_wav_parser_rejects_unknown_codec_with_replayable_prefix():
    wav = _wav(b"\x00" * 64, rate=8000, bits=4, tag=0x11)
    parser = WavStreamParser()
    with pytest.raises(Exception) as info:
        parser.feed(wav)
    assert wav.startswith(info.value.prefix)


def test_pcm_converter_drops_incomplete_trailing_frame():
    conv = PcmToPcm16k(rate=16000)
    assert conv.feed(b"\x01\x00\x02") == b"\x01\x00"
    assert conv.finish() == b""


def _mp3(seconds: int = 1) -> bytes:
    return subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate=24000",
            "-ac", "1", "-b:a", "48k", "-f", "mp3", "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout


@needs_ffmpeg
def test_mp3_is_decoded_by_streaming_ffmpeg():
    out = _collect(_split(_mp3(), [333, 1, 4096]), "audio/mpeg")
    samples = _samples(out)
    # MP3 編碼器會在頭尾補幾十 ms 的 padding。
    assert 15000 <= len(samples) <= 17500
    # lavfi sine 預設振幅是滿刻度的 1/8（約 4096）。
    assert max(abs(v) for v in samples) > 3000


@needs_ffmpeg
def test_ffmpeg_stops_when_consumer_stops_early():
    mp3 = _mp3(5)
    procs = []
    real_exec = asyncio.create_subprocess_exec

    async def spy_exec(*args, **kwargs):
        proc = await real_exec(*args, **kwargs)
        procs.append(proc)
        return proc

    async def endless():
        while True:
            yield mp3
            await asyncio.sleep(0)

    async def run():
        gen = ffmpeg_to_pcm16k(endless())
        first = await gen.__anext__()
        assert first
        await gen.aclose()
        # 客戶端斷線後 ffmpeg 不能留著當殭屍程序。
        assert procs and procs[0].returncode is not None

    asyncio.create_subprocess_exec = spy_exec
    try:
        asyncio.run(asyncio.wait_for(run(), timeout=10))
    finally:
        asyncio.create_subprocess_exec = real_exec

    asyncio.run(asyncio.wait_for(run(), timeout=5))


def test_empty_source_yields_nothing():
    assert _collect([], "audio/mpeg") == b""


@needs_ffmpeg
def test_wav_with_codec_not_handled_in_process_falls_back_to_ffmpeg():
    mulaw = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1:sample_rate=8000",
            "-c:a", "pcm_mulaw", "-f", "wav", "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout
    # 一整塊送進來（大於切片大小），fallback 時不能漏掉還沒餵給解析器的部分。
    out = _samples(_collect([mulaw], "audio/wav"))
    assert 15800 <= len(out) <= 16200


def test_resampling_does_not_hold_the_event_loop() -> None:
    # PR Agent 2026-10-14：重採樣若直接在 async generator 裡算，一路 TTS 會卡住其他請求。
    import asyncio
    import time

    from app import tts_pcm

    pcm24k = (b"\x10\x00\x20\x00") * 48000  # 4 秒 24 kHz

    async def source():
        for i in range(0, len(pcm24k), 8192):
            yield pcm24k[i:i + 8192]

    async def main():
        gaps = []
        stop = False

        async def ticker():
            last = time.monotonic()
            while not stop:
                await asyncio.sleep(0.001)
                now = time.monotonic()
                gaps.append(now - last)
                last = now

        tick = asyncio.create_task(ticker())
        out = b""
        async for chunk in tts_pcm.convert_to_pcm16k(source(), "audio/l16;rate=24000;channels=1"):
            out += chunk
        stop = True
        await tick
        return out, max(gaps)

    out, worst_gap = asyncio.run(main())
    assert len(out) > 0
    assert worst_gap < 0.05
