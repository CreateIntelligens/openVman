"""Simulate N people using an embedded avatar page: ask, listen to the whole reply, pause, ask again.

Each simulated person follows the SDK `ask()` protocol without drawing the avatar:
`/api/v1/chat/stream`, and once `done` arrives the whole reply is spoken with one
`/api/v1/tts/stream` request (`format=pcm16k`). A reply counts as heard to the end when its last audio
would finish playing (16 kHz s16le: 32,000 bytes per second, measured from the first
audio byte); the person then waits 2-3 seconds and asks the next question.

    LOAD_EMBED_KEY=... LOAD_ORIGIN=https://... python3 users_e2e.py --base https://... \
        --project <id> --users 50 --rounds 5 --questions questions.json --out run.json

Output matches `burst_nodes.py` (one record per question, epoch timestamps, trace_id),
so `node_report.py` works on it; each record also has `user`, `round`, `tts_requests`,
`audio_seconds` and `heard_end`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
import uuid
from pathlib import Path

import httpx

from burst_nodes import login

PCM_BYTES_PER_SECOND = 16000 * 2


async def speak_reply(client, base, headers, args, text: str, record: dict) -> None:
    """Synthesize the whole reply with one request, the way the SDK does after `done`."""
    payload = {"text": text, "project_id": args.project, "format": "pcm16k"}
    if args.tts_provider:
        payload["provider"] = args.tts_provider
    if args.tts_voice:
        payload["voice"] = args.tts_voice
    record["tts_requests"] = 1
    record["tts_send"] = time.time()
    total_bytes = 0
    async with client.stream("POST", f"{base}/api/v1/tts/stream", headers=headers, json=payload) as response:
        record["tts_status"] = response.status_code
        record["tts_provider"] = response.headers.get("x-tts-provider", "")
        if response.status_code >= 400:
            record["tts_error"] = f"http {response.status_code}"
        async for chunk in response.aiter_bytes():
            if chunk and response.status_code < 400:
                record.setdefault("tts_first_byte", time.time())
                total_bytes += len(chunk)
    record["audio_seconds"] = round(total_bytes / PCM_BYTES_PER_SECOND, 2)
    if "tts_first_byte" in record:
        # 播放從第一段音訊開始，照音訊長度推算唸完的時間；合成比播放慢時以最後收到的時間為準。
        record["heard_end"] = max(record["tts_first_byte"] + record["audio_seconds"], time.time())


async def ask(client, base, headers, args, session_id, question, user, round_index) -> dict:
    record: dict = {"user": user, "round": round_index, "session_id": session_id,
                    "question": question, "send": time.time(), "ok": False}
    reply = ""
    try:
        async with client.stream(
            "POST", f"{base}/api/v1/chat/stream", headers=headers,
            json={"project_id": args.project, "session_id": session_id, "message": question},
        ) as response:
            record["headers"] = time.time()
            record["status"] = response.status_code
            if response.status_code >= 400:
                record["error"] = f"http {response.status_code}"
            else:
                event = ""
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data = json.loads(line[5:]) if line[5:].strip() else {}
                        if event == "sentence":
                            record.setdefault("first_sentence", time.time())
                        elif event == "done":
                            record["done"] = time.time()
                            record["trace_id"] = data.get("trace_id", "")
                            record["ok"] = True
                            reply = data.get("reply") or ""
                            record.setdefault("first_sentence", record["done"])
                        elif event == "error":
                            record["error"] = json.dumps(data, ensure_ascii=False)[:300]
    except Exception as error:  # noqa: BLE001 — every failure is data
        record["error"] = f"{type(error).__name__}: {error}"[:300]
    if not reply:
        return record
    try:
        await speak_reply(client, base, headers, args, reply, record)
    except Exception as error:  # noqa: BLE001
        record["tts_error"] = f"{type(error).__name__}: {error}"[:300]
    return record


async def person(client, base, headers, args, run_id, user, questions, start_at, records) -> None:
    await asyncio.sleep(max(0.0, start_at - time.time()))
    # SDK 一個 instance 沿用同一組 session_id，每位使用者一段對話。
    session_id = f"users-{run_id}-{user}"
    rng = random.Random(f"{run_id}-{user}")
    for round_index in range(args.rounds):
        question = questions[(user + round_index * 7) % len(questions)]
        record = await ask(client, base, headers, args, session_id, question, user, round_index)
        records.append(record)
        listened_until = record.get("heard_end") or record.get("done") or time.time()
        await asyncio.sleep(max(0.0, listened_until - time.time()) + rng.uniform(2.0, 3.0))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--ramp", type=float, default=10.0, help="seconds over which people start")
    parser.add_argument("--questions", required=True)
    parser.add_argument("--tts-provider", default="")
    parser.add_argument("--tts-voice", default="")
    parser.add_argument("--label", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args()

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    run_id = uuid.uuid4().hex[:8]
    records: list[dict] = []
    limits = httpx.Limits(max_connections=args.users * 4, max_keepalive_connections=args.users * 4)
    async with httpx.AsyncClient(timeout=120, limits=limits, verify=not args.insecure) as client:
        headers = await login(client, args.base)
        started = time.time() + 1.0
        await asyncio.gather(*(
            person(client, args.base, headers, args, run_id, user, questions,
                   started + args.ramp * user / max(1, args.users), records)
            for user in range(args.users)
        ))
    records.sort(key=lambda record: record["send"])
    for index, record in enumerate(records):
        record["index"] = index
    Path(args.out).write_text(json.dumps({
        "label": args.label, "run_id": run_id, "base": args.base, "project": args.project,
        "count": len(records), "users": args.users, "rounds": args.rounds, "window": args.ramp,
        "tts_provider": args.tts_provider, "started": started, "finished": time.time(),
        "records": records,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for record in records if record["ok"])
    print(f"run {run_id}: {ok}/{len(records)} ok, {args.users} users x {args.rounds} -> {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
