"""Send N chat questions within a window (default 100 in 1 second) and time every step.

Each question goes through Backend `/api/v1/chat/stream` the way the avatar front end
does: when the first sentence arrives it is sent to `/api/v1/tts/stream` and the
first audio byte is timed. All timestamps are epoch seconds, so `node_report.py`
can line them up with Backend and Brain log lines (same host clock) by `trace_id`.

    python3 burst_nodes.py --base https://example --project <id> --out run.json
    # credentials: LOAD_TOKEN=<bearer>, LOAD_USERNAME / LOAD_PASSWORD to log in,
    # or LOAD_EMBED_KEY + LOAD_ORIGIN (an allowlisted origin) like an embedded page

Sessions are named `burst-<run>-<n>` so they can be found and removed afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import httpx


async def login(client: httpx.AsyncClient, base: str) -> dict[str, str]:
    embed_key = os.environ.get("LOAD_EMBED_KEY", "").strip()
    if embed_key:
        # 公開網頁的接法：embed key 加上白名單內的 Origin，跟 SDK 的對話模式一樣。
        return {"X-Embed-Key": embed_key, "Origin": os.environ.get("LOAD_ORIGIN", "")}
    token = os.environ.get("LOAD_TOKEN", "").strip()
    if not token:
        response = await client.post(
            f"{base}/api/v1/auth/login",
            json={"username": os.environ["LOAD_USERNAME"], "password": os.environ["LOAD_PASSWORD"]},
        )
        response.raise_for_status()
        token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


async def speak(client, base, headers, args, text) -> dict:
    record: dict = {"tts_send": time.time()}
    payload = {"text": text, "project_id": args.project, "format": "pcm16k"}
    if args.tts_provider:
        payload["provider"] = args.tts_provider
    if args.tts_voice:
        payload["voice"] = args.tts_voice
    async with client.stream("POST", f"{base}/api/v1/tts/stream", headers=headers, json=payload) as response:
        record["tts_headers"] = time.time()
        record["tts_status"] = response.status_code
        record["tts_provider"] = response.headers.get("x-tts-provider", "")
        size = 0
        async for chunk in response.aiter_bytes():
            # 錯誤回應的內容不是聲音，不能算成「聽到第一句」。
            if chunk and response.status_code < 400 and "tts_first_byte" not in record:
                record["tts_first_byte"] = time.time()
            size += len(chunk)
        if response.status_code >= 400:
            record["tts_error"] = f"http {response.status_code}"
        record["tts_done"] = time.time()
        record["tts_bytes"] = size
    return record


async def ask(client, base, headers, args, run_id, index, question, start_at) -> dict:
    await asyncio.sleep(max(0.0, start_at - time.time()))
    session_id = f"burst-{run_id}-{index}"
    record: dict = {"index": index, "session_id": session_id, "question": question, "send": time.time(), "ok": False}
    tts_task = None
    try:
        async with client.stream(
            "POST", f"{base}/api/v1/chat/stream", headers=headers,
            json={"project_id": args.project, "session_id": session_id, "message": question},
        ) as response:
            record["headers"] = time.time()
            record["status"] = response.status_code
            record["request_id"] = response.headers.get("x-request-id", "")
            if response.status_code >= 400:
                record["error"] = f"http {response.status_code}"
                return record
            event = ""
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:]) if line[5:].strip() else {}
                    if event == "sentence" and "first_sentence" not in record:
                        record["first_sentence"] = time.time()
                        if not args.no_tts:
                            tts_task = asyncio.create_task(
                                speak(client, base, headers, args, data.get("tts_text") or data.get("text", "")),
                            )
                    elif event == "done":
                        record["done"] = time.time()
                        record["trace_id"] = data.get("trace_id", "")
                        record["answer_source"] = data.get("answer_source", "")
                        record["no_answer"] = data.get("no_answer")
                        record["ok"] = True
                    elif event == "error":
                        record["error"] = json.dumps(data, ensure_ascii=False)[:300]
    except Exception as error:  # noqa: BLE001 — every failure is data for the report
        record["error"] = f"{type(error).__name__}: {error}"[:300]
    if tts_task is not None:
        try:
            record.update(await tts_task)
        except Exception as error:  # noqa: BLE001
            record["tts_error"] = f"{type(error).__name__}: {error}"[:300]
    return record


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--window", type=float, default=1.0, help="seconds over which the questions start")
    parser.add_argument("--questions", default=str(Path(__file__).with_name("questions-industrial.json")))
    parser.add_argument("--tts-provider", default="")
    parser.add_argument("--tts-voice", default="")
    parser.add_argument("--no-tts", action="store_true")
    parser.add_argument("--label", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification (self-signed dev certs)")
    args = parser.parse_args()

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    run_id = uuid.uuid4().hex[:8]
    limits = httpx.Limits(max_connections=args.count * 3, max_keepalive_connections=args.count * 3)
    async with httpx.AsyncClient(timeout=120, limits=limits, verify=not args.insecure) as client:
        headers = await login(client, args.base)
        started = time.time() + 1.0
        records = await asyncio.gather(*(
            ask(client, args.base, headers, args, run_id, index, questions[index % len(questions)],
                started + args.window * index / max(1, args.count))
            for index in range(args.count)
        ))
    Path(args.out).write_text(json.dumps({
        "label": args.label, "run_id": run_id, "base": args.base, "project": args.project,
        "count": args.count, "window": args.window, "tts_provider": args.tts_provider,
        "started": started, "finished": time.time(), "records": records,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for record in records if record["ok"])
    print(f"run {run_id}: {ok}/{len(records)} ok -> {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
