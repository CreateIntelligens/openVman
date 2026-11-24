"""Pure-Python reference resampler, kept only to check the numpy version.

This is the implementation `app.tts_pcm.StreamingResampler` used before it was
vectorised; the tests compare the two sample by sample.
"""

from __future__ import annotations

import math
import sys
from array import array
from collections.abc import Sequence
from operator import mul

PCM16K_RATE = 16000
_BIG_ENDIAN = sys.byteorder == "big"


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


class ReferenceResampler:
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
