"""Follow-up measurements for A (Gemini Live fed a whole clip, manual activity).

Talks to Gemini Live directly with the same messages as ingestion_audio, timing each stage.
Credentials as in README.md. Writes JSON to $GEMINI_ASR_DATA/results/live_<cmd>_<stamp>.json.

    python3 live_probe.py stages   [--reps 3]             # Q1 per-stage latency, fresh session per clip
    python3 live_probe.py reuse    [--rounds 2]           # Q2 many clips in one session vs fresh
    python3 live_probe.py idle                            # Q2/Q3 idle gaps: used session and setup-only session
    python3 live_probe.py pool     [--size 2] [--gap 1]   # Q3 warm pool prototype vs cold
    python3 live_probe.py padding  [--reps 3]             # Q4 lead/tail silence grid
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# bench 會把 backend/ 放進 sys.path 並替身 anydoc，必須先 import。
import bench
import websockets

from app.gateway import gemini_transcription as gemini
from app.gateway import ingestion_audio

CHUNK = 3200


def _key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        sys.exit("GEMINI_API_KEY is not set")
    return key


def _clips(pattern: str = "idx_*") -> list[dict]:
    import fnmatch

    out = []
    for clip in bench.clips():
        if fnmatch.fnmatch(clip["file"], pattern) and clip["reference"]:
            clip["pcm"] = ingestion_audio._decode_pcm16(clip["path"])
            out.append(clip)
    return out


def _silence(seconds: float) -> bytes:
    return b"\0\0" * int(gemini.SAMPLE_RATE * seconds)


class Session:
    """One Live session in manual-activity mode; can transcribe several clips in turn."""

    def __init__(self) -> None:
        self.ws = None
        self.timing: dict = {}
        self.opened_at = 0.0
        self.go_away = False
        self.uses = 0
        self.last_active = 0.0

    async def open(self) -> Session:
        t0 = time.monotonic()
        self.ws = await websockets.connect(
            gemini.GEMINI_LIVE_URL, additional_headers={"x-goog-api-key": _key()},
            max_size=4 << 20, open_timeout=10,
        )
        t1 = time.monotonic()
        await self.ws.send(gemini.setup_message(
            gemini.transcription_config(["en-US"]), manual_activity=True,
        ))
        first = json.loads(await asyncio.wait_for(self.ws.recv(), 10))
        if "setupComplete" not in first:
            raise RuntimeError("setup rejected")
        t2 = time.monotonic()
        self.timing = {"connect_s": t1 - t0, "setup_s": t2 - t1}
        self.opened_at = t2
        return self

    async def transcribe(self, pcm: bytes, lead: float = 0.5, tail: float = 0.5,
                         timeout: float = 30) -> dict:
        padded = _silence(lead) + pcm + _silence(tail)
        t0 = time.monotonic()
        await self.ws.send(gemini.ACTIVITY_START)
        for i in range(0, len(padded), CHUNK):
            await self.ws.send(gemini.audio_message(padded[i:i + CHUNK]))
        await self.ws.send(gemini.ACTIVITY_END)
        t1 = time.monotonic()
        finals, interims, done_by, first_msg = [], 0, "timeout", None
        deadline = t1 + timeout
        settle = None
        while True:
            now = time.monotonic()
            wait = deadline - now
            if settle is not None:
                wait = min(wait, settle - now)
            if wait <= 0:
                done_by = "activity_end" if settle is not None else "timeout"
                break
            try:
                raw = await asyncio.wait_for(self.ws.recv(), wait)
            except asyncio.TimeoutError:
                continue
            first_msg = first_msg or time.monotonic()
            self.go_away |= '"goAway"' in str(raw)
            event = gemini.parse_live_message(raw)
            interims += bool(event.interim)
            if event.final.strip():
                finals.append(event.final.strip())
            if event.generation_complete:
                done_by = "generation_complete"
                break
            if event.voice_activity == "ACTIVITY_END" and settle is None:
                settle = time.monotonic() + 0.5
        t2 = time.monotonic()
        self.uses += 1
        # 同一條連線要接下一句：把這段話的 ACTIVITY_END 讀掉，不讓它落到下一句（不算進延遲）。
        if done_by == "generation_complete":
            try:
                while True:
                    raw = await asyncio.wait_for(self.ws.recv(), 0.5)
                    self.go_away |= '"goAway"' in str(raw)
                    event = gemini.parse_live_message(raw)
                    if event.voice_activity == "ACTIVITY_END":
                        break
            except asyncio.TimeoutError:
                pass
        return {
            "send_s": t1 - t0, "wait_s": t2 - t1, "finals": finals, "interims": interims,
            "text": " ".join(finals), "completed_by": done_by,
            "first_msg_s": (first_msg - t1) if first_msg else None,
        }

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 3)


def _score(clip: dict, text: str) -> dict:
    ref, hyp = bench.normalize(clip["reference"]).split(), bench.normalize(text).split()
    return {
        "wer": round(bench.wer(clip["reference"], text), 3),
        "exact": ref == hyp,
        "first_word_ok": bool(hyp) and hyp[0] == ref[0],
    }


def _save(cmd: str, payload: dict) -> Path:
    bench.RESULTS.mkdir(parents=True, exist_ok=True)
    path = bench.RESULTS / f"live_{cmd}_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", path)
    return path


def _stats(values: list[float]) -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "n/a"
    return f"med {statistics.median(values):.3f} p90 {bench._pct(values, 0.9):.3f} (n={len(values)})"


async def _fresh(clip: dict, lead=0.5, tail=0.5) -> dict:
    t0 = time.monotonic()
    session = Session()
    try:
        await session.open()
        result = await session.transcribe(clip["pcm"], lead, tail)
    finally:
        await session.close()
    return {**{k: _r(v) for k, v in session.timing.items()},
            **{k: (_r(v) if isinstance(v, float) else v) for k, v in result.items()},
            "total_s": _r(time.monotonic() - t0), **_score(clip, result["text"])}


async def cmd_stages(args) -> None:
    clips = _clips()
    rows = []
    for rep in range(args.reps):
        for clip in clips:
            t0 = time.monotonic()
            ingestion_audio._decode_pcm16(clip["path"])
            decode = time.monotonic() - t0
            try:
                row = await _fresh(clip)
            except Exception as exc:  # noqa: BLE001
                row = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}
            row.update(file=clip["file"], rep=rep, decode_s=_r(decode), audio_s=clip["duration_s"])
            rows.append(row)
            print(rep, clip["file"], {k: row.get(k) for k in
                  ("connect_s", "setup_s", "send_s", "wait_s", "total_s", "text")}, flush=True)
    ok = [r for r in rows if "error" not in r]
    for key in ("decode_s", "connect_s", "setup_s", "send_s", "wait_s", "first_msg_s", "total_s"):
        print(f"{key:12} {_stats([r[key] for r in ok])}")
    print("exact", sum(r["exact"] for r in ok), "/", len(ok), "errors", len(rows) - len(ok))
    _save("stages", {"rows": rows})


async def cmd_reuse(args) -> None:
    clips = _clips()
    rounds = []
    for n in range(args.rounds):
        order = clips if n % 2 == 0 else list(reversed(clips))
        session = await Session().open()
        rows = []
        try:
            for i, clip in enumerate(order):
                try:
                    result = await session.transcribe(clip["pcm"])
                except Exception as exc:  # noqa: BLE001
                    rows.append({"file": clip["file"], "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
                    print("ERR", clip["file"], exc, flush=True)
                    break
                prev = order[i - 1]["reference"] if i else ""
                # 洩漏判斷：結果比參考多出字，且多出的字出現在上一句參考裡。
                extra = set(bench.normalize(result["text"]).split()) - set(bench.normalize(clip["reference"]).split())
                leak = bool(extra & set(bench.normalize(prev).split())) if prev else False
                rows.append({"file": clip["file"], "index": i, "send_s": _r(result["send_s"]),
                             "wait_s": _r(result["wait_s"]), "user_s": _r(result["send_s"] + result["wait_s"]),
                             "text": result["text"], "finals": len(result["finals"]),
                             "completed_by": result["completed_by"], "leak_suspect": leak,
                             **_score(clip, result["text"])})
                print(n, i, clip["file"], rows[-1]["user_s"], result["text"], "LEAK?" if leak else "", flush=True)
        finally:
            await session.close()
        rounds.append({"setup": {k: _r(v) for k, v in session.timing.items()}, "rows": rows})
    all_rows = [r for rd in rounds for r in rd["rows"] if "error" not in r]
    print("reused user_s", _stats([r["user_s"] for r in all_rows]))
    print("exact", sum(r["exact"] for r in all_rows), "/", len(all_rows),
          "leak suspects", sum(r["leak_suspect"] for r in all_rows))
    _save("reuse", {"rounds": rounds})


async def cmd_idle(args) -> None:
    clips = _clips()
    clip = next(c for c in clips if c["file"] == "idx_hayley_q02.wav")
    gaps = [float(g) for g in args.gaps.split(",")]
    setup_waits = [float(g) for g in args.setup_waits.split(",")]

    async def used_session() -> list[dict]:
        """One clip, idle gap, next clip … in one session (gaps accumulate)."""
        out = []
        session = await Session().open()
        try:
            r = await session.transcribe(clip["pcm"])
            out.append({"gap_s": 0, "user_s": _r(r["send_s"] + r["wait_s"]), "text": r["text"]})
            for gap in gaps:
                await asyncio.sleep(gap)
                age = time.monotonic() - session.opened_at
                try:
                    r = await session.transcribe(clip["pcm"])
                    out.append({"gap_s": gap, "session_age_s": _r(age),
                                "user_s": _r(r["send_s"] + r["wait_s"]), "text": r["text"],
                                "completed_by": r["completed_by"]})
                except Exception as exc:  # noqa: BLE001
                    out.append({"gap_s": gap, "session_age_s": _r(age),
                                "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
                    break
                print("used gap", gap, out[-1], flush=True)
        finally:
            await session.close()
        return out

    async def setup_only(wait: float) -> dict:
        """Connect + setup, send nothing for `wait` s, then one clip (pool idle bound)."""
        session = await Session().open()
        try:
            await asyncio.sleep(wait)
            try:
                r = await session.transcribe(clip["pcm"])
                out = {"idle_s": wait, "user_s": _r(r["send_s"] + r["wait_s"]), "text": r["text"],
                       "completed_by": r["completed_by"]}
            except Exception as exc:  # noqa: BLE001
                out = {"idle_s": wait, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        finally:
            await session.close()
        print("setup-only", out, flush=True)
        return out

    results = await asyncio.gather(
        used_session(), *(setup_only(w) for w in setup_waits), return_exceptions=True,
    )
    payload = {
        "used_session": results[0] if not isinstance(results[0], Exception) else repr(results[0]),
        "setup_only": [r if not isinstance(r, Exception) else repr(r) for r in results[1:]],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    _save("idle", payload)


async def cmd_idle2(args) -> None:
    """Finer idle bound: setup-only vs used-once sessions, and a silence keepalive."""
    clip = next(c for c in _clips() if c["file"] == "idx_hayley_q02.wav")

    async def probe(kind: str, wait: float) -> dict:
        session = await Session().open()
        try:
            if kind == "used":
                await session.transcribe(clip["pcm"])
            started = time.monotonic()
            if kind == "keepalive":
                # 不開 activity，只送 100 ms 靜音，看能不能撐過閒置上限（是否計費未測）。
                while time.monotonic() - started < wait:
                    await asyncio.sleep(min(args.keepalive, wait - (time.monotonic() - started)))
                    await session.ws.send(gemini.audio_message(_silence(0.1)))
            else:
                await asyncio.sleep(wait)
            try:
                r = await session.transcribe(clip["pcm"])
                out = {"kind": kind, "idle_s": wait, "user_s": _r(r["send_s"] + r["wait_s"]),
                       "text": r["text"], "completed_by": r["completed_by"]}
            except Exception as exc:  # noqa: BLE001
                out = {"kind": kind, "idle_s": wait, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        finally:
            await session.close()
        print(out, flush=True)
        return out

    plan = [("setup", w) for w in (40, 50, 60, 75, 90)] + [("used", w) for w in (40, 60, 90)] + \
        [("keepalive", w) for w in (150, 330)]
    results = await asyncio.gather(*(probe(k, w) for k, w in plan), return_exceptions=True)
    _save("idle2", {"results": [r if not isinstance(r, Exception) else repr(r) for r in results]})


class Pool:
    """Prototype: N sessions already connected and set up; take one, close after use, refill."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.ready: asyncio.Queue[Session] = asyncio.Queue()
        self.refills: set[asyncio.Task] = set()

    async def start(self) -> None:
        sessions = await asyncio.gather(*(Session().open() for _ in range(self.size)))
        for session in sessions:
            self.ready.put_nowait(session)

    def _refill(self) -> None:
        async def one() -> None:
            self.ready.put_nowait(await Session().open())

        task = asyncio.create_task(one())
        self.refills.add(task)
        task.add_done_callback(self.refills.discard)

    async def take(self) -> tuple[Session, bool]:
        try:
            session, warm = self.ready.get_nowait(), True
        except asyncio.QueueEmpty:
            session, warm = await Session().open(), False
        self._refill()
        return session, warm

    async def close(self) -> None:
        await asyncio.gather(*self.refills, return_exceptions=True)
        while not self.ready.empty():
            await self.ready.get_nowait().close()


async def cmd_pool(args) -> None:
    clips = _clips()
    pool = Pool(args.size)
    await pool.start()
    rows = []
    try:
        for rep in range(args.reps):
            for clip in clips:
                t0 = time.monotonic()
                session, warm = await pool.take()
                try:
                    r = await session.transcribe(clip["pcm"])
                finally:
                    asyncio.create_task(session.close())
                user = time.monotonic() - t0
                rows.append({"file": clip["file"], "rep": rep, "warm": warm, "user_s": _r(user),
                             "text": r["text"], **_score(clip, r["text"])})
                print(rep, clip["file"], "warm" if warm else "COLD", round(user, 3), r["text"], flush=True)
                await asyncio.sleep(args.gap)
    finally:
        await pool.close()
    warm = [r["user_s"] for r in rows if r["warm"]]
    cold = [r["user_s"] for r in rows if not r["warm"]]
    print("warm", _stats(warm), "| cold-in-pool", _stats(cold))
    _save("pool", {"size": args.size, "gap_s": args.gap, "rows": rows})


async def cmd_padding(args) -> None:
    clips = _clips() + _clips("q04_*")
    leads = [float(x) for x in args.leads.split(",")]
    tails = [float(x) for x in args.tails.split(",")]
    rows = []
    for rep in range(args.reps):
        for lead in leads:
            for tail in tails:
                for clip in clips:
                    try:
                        row = await _fresh(clip, lead, tail)
                    except Exception as exc:  # noqa: BLE001
                        row = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}
                    row.update(file=clip["file"], rep=rep, lead=lead, tail=tail)
                    rows.append(row)
                    print(rep, lead, tail, clip["file"], row.get("total_s"), row.get("text"), flush=True)
    _save("padding", {"rows": rows})
    for lead in leads:
        for tail in tails:
            rs = [r for r in rows if r["lead"] == lead and r["tail"] == tail
                  and "error" not in r and r["file"].startswith("idx_")]
            print(f"lead {lead} tail {tail}: exact {sum(r['exact'] for r in rs)}/{len(rs)} "
                  f"first-word {sum(r['first_word_ok'] for r in rs)}/{len(rs)} "
                  f"send+wait {_stats([r['send_s'] + r['wait_s'] for r in rs])}")


class SharedPool:
    """Warm Live sessions for one (api_key_id, project_id); design under evaluation.

    mode=single：拿一條就用一次、用完關掉，背景補回 target 條——session 之間沒有任何上下文。
    mode=reuse：用完健康（正常收尾、只有一個 final、沒疑似串句）就放回去給下一個請求。
    全忙或沒有閒置時當場開一條（miss）。閒置超過 idle_ttl、年齡超過 max_age（文件：連線約
    10 分鐘）或收到 goAway 的 session 由背景維護關掉並補新的。
    """

    def __init__(self, target: int, mode: str, idle_ttl: float, max_age: float) -> None:
        self.target, self.mode, self.idle_ttl, self.max_age = target, mode, idle_ttl, max_age
        self.idle: list[Session] = []
        self.opening = 0
        self.open_count = self.peak = self.created = self.expired = 0
        self.maintainer: asyncio.Task | None = None

    async def start(self) -> None:
        await asyncio.gather(*(self._fill() for _ in range(self.target)))
        self.maintainer = asyncio.create_task(self._maintain())

    async def _new(self) -> Session:
        self.opening += 1
        try:
            session = await Session().open()
        finally:
            self.opening -= 1
        session.last_active = time.monotonic()
        self.created += 1
        self.open_count += 1
        self.peak = max(self.peak, self.open_count)
        return session

    async def _fill(self) -> None:
        try:
            self.idle.append(await self._new())
        except Exception as exc:  # noqa: BLE001
            print("refill failed", type(exc).__name__, flush=True)

    def _fresh_enough(self, session: Session) -> bool:
        now = time.monotonic()
        return (not session.go_away and now - session.opened_at < self.max_age
                and now - session.last_active < self.idle_ttl)

    async def _maintain(self) -> None:
        while True:
            for session in [s for s in self.idle if not self._fresh_enough(s)]:
                self.idle.remove(session)
                self.expired += 1
                await self._drop(session)
            for _ in range(self.target - len(self.idle) - self.opening):
                asyncio.create_task(self._fill())
            await asyncio.sleep(1)

    async def acquire(self) -> tuple[Session, str]:
        while self.idle:
            session = self.idle.pop()
            if self._fresh_enough(session):
                return session, "hit"
            self.expired += 1
            await self._drop(session)
        return await self._new(), "miss"

    async def release(self, session: Session, healthy: bool) -> None:
        session.last_active = time.monotonic()
        if self.mode == "reuse" and healthy and self._fresh_enough(session):
            self.idle.append(session)
        else:
            await self._drop(session)

    async def _drop(self, session: Session) -> None:
        self.open_count -= 1
        await session.close()

    async def close(self) -> None:
        if self.maintainer:
            self.maintainer.cancel()
        while self.idle:
            await self._drop(self.idle.pop())


async def cmd_shared(args) -> None:
    import random

    clips = _clips()
    pool = SharedPool(args.size, args.mode, args.idle_ttl, args.max_age)
    await pool.start()
    # 第二層：帶 session_id 的呼叫端釘住自己的 session（key = (api_key_id, project_id, session_id)）。
    pinned: dict[tuple, Session] = {}
    busy: set[tuple] = set()
    rows: list[dict] = []
    last_text: dict[int, str] = {}
    gaps = [float(g) for g in args.gaps.split(",")]

    async def caller(cid: int) -> None:
        rng = random.Random(cid)
        pin_key = ("key-1", "proj-1", f"chat-{cid}") if cid < args.pinned_callers else None
        for rep in range(args.reps):
            order = clips[:]
            rng.shuffle(order)
            for clip in order:
                t0 = time.monotonic()
                source = None
                if pin_key and pin_key not in busy and (s := pinned.get(pin_key)) and pool._fresh_enough(s):
                    session, source = s, "pinned"
                else:
                    session, source = await pool.acquire()
                    if pin_key and pin_key not in busy:
                        pinned[pin_key], source = session, f"pin-new({source})"
                if pin_key:
                    busy.add(pin_key)
                prev = last_text.get(id(session), "")
                healthy, err = False, None
                try:
                    r = await session.transcribe(clip["pcm"])
                    healthy = r["completed_by"] == "generation_complete" and len(r["finals"]) == 1
                except Exception as exc:  # noqa: BLE001
                    r = {"text": "", "finals": [], "completed_by": "error"}
                    err = f"{type(exc).__name__}: {exc}"[:160]
                user = time.monotonic() - t0
                extra = set(bench.normalize(r["text"]).split()) - set(bench.normalize(clip["reference"]).split())
                bleed = bool(extra & set(bench.normalize(prev).split())) if prev else False
                last_text[id(session)] = r["text"]
                if pin_key and pinned.get(pin_key) is session:
                    busy.discard(pin_key)
                    session.last_active = time.monotonic()
                    if not healthy or bleed:
                        pinned.pop(pin_key)
                        await pool._drop(session)
                else:
                    await pool.release(session, healthy and not bleed)
                rows.append({"caller": cid, "file": clip["file"], "source": source, "user_s": _r(user),
                             "uses_before": session.uses - 1, "text": r["text"], "bleed_suspect": bleed,
                             "error": err, "open_sessions": pool.open_count, **_score(clip, r["text"])})
                print(cid, clip["file"], source, round(user, 3), pool.open_count, r["text"],
                      err or "", "BLEED?" if bleed else "", flush=True)
                await asyncio.sleep(rng.choice(gaps))

    try:
        await asyncio.gather(*(caller(i) for i in range(args.callers)))
    finally:
        for session in pinned.values():
            await pool._drop(session)
        await pool.close()
    for source in sorted({r["source"] for r in rows}):
        print(f"{source:16} {_stats([r['user_s'] for r in rows if r['source'] == source])}")
    print("exact", sum(r["exact"] for r in rows), "/", len(rows), "bleed", sum(r["bleed_suspect"] for r in rows),
          "errors", sum(bool(r["error"]) for r in rows), "created", pool.created, "peak open", pool.peak,
          "expired", pool.expired)
    _save("shared", {"args": vars(args), "created": pool.created, "peak": pool.peak,
                     "expired": pool.expired, "rows": rows})


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("stages")
    p.add_argument("--reps", type=int, default=3)
    p = sub.add_parser("reuse")
    p.add_argument("--rounds", type=int, default=2)
    p = sub.add_parser("idle")
    p.add_argument("--gaps", default="30,120,300")
    p.add_argument("--setup-waits", default="30,120,300,600,720")
    p = sub.add_parser("idle2")
    p.add_argument("--keepalive", type=float, default=15.0)
    p = sub.add_parser("pool")
    p.add_argument("--size", type=int, default=2)
    p.add_argument("--gap", type=float, default=1.0)
    p.add_argument("--reps", type=int, default=2)
    p = sub.add_parser("shared")
    p.add_argument("--callers", type=int, default=1)
    p.add_argument("--pinned-callers", type=int, default=0)
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--size", type=int, default=1)
    p.add_argument("--mode", choices=["single", "reuse"], default="single")
    p.add_argument("--gaps", default="0.5,2,5", help="seconds between a caller's requests (random choice)")
    p.add_argument("--idle-ttl", type=float, default=25.0)
    p.add_argument("--max-age", type=float, default=540.0)
    p = sub.add_parser("padding")
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--leads", default="0.1,0.2,0.3,0.5")
    p.add_argument("--tails", default="0,0.2,0.5")
    args = parser.parse_args()
    asyncio.run(globals()[f"cmd_{args.cmd}"](args))


if __name__ == "__main__":
    main()
