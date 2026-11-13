"""Local OpenAI-compatible responder: first answer content after 0.8 seconds."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
counts = {"requests": 0, "streams": 0}


@app.get("/stats")
async def stats():
    return counts


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": "synthetic-chat", "object": "model"}]}


@app.post("/v1/chat/completions")
async def completion(request: Request):
    body = await request.json()
    counts["requests"] += 1
    latest_user = next((message.get("content", "") for message in reversed(body.get("messages", [])) if message.get("role") == "user"), "")
    tools = body.get("tools", [])
    has_skill = any("worker_probe" in tool.get("function", {}).get("name", "") for tool in tools)
    if "隔離技能狀態" in str(latest_user):
        content = "隔離技能已啟用。" if has_skill else "隔離技能已停用。"
    else:
        content = "服務中心週末提供預約諮詢。請攜帶預約確認單。"
    base = {"id": "synthetic-completion", "object": "chat.completion", "created": int(time.time()), "model": body.get("model", "synthetic-chat")}
    if not body.get("stream"):
        await asyncio.sleep(0.8)
        return {**base, "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
    counts["streams"] += 1

    async def events():
        await asyncio.sleep(0.8)
        for text in content.split("。"):
            if text:
                chunk = {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": text + "。"}, "finish_reason": None}]}
                yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
                await asyncio.sleep(0.02)
        yield "data: " + json.dumps({**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, access_log=False)
