"""Verify actual batch and streamed Edge audio through the disposable browser edge."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import httpx
from bootstrap import PASSWORD, PROJECT


def run(base: str, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with httpx.Client(base_url=base, timeout=35, trust_env=False) as client:
        response = client.post("/api/v1/auth/login", json={"username": "worker-load", "password": PASSWORD})
        response.raise_for_status()
        headers = {"Authorization": "Bearer " + response.json()["token"]}
        for name, route, payload in (
            ("batch", "/v1/audio/speech", {"input": "這是批次語音的隔離驗收。", "response_format": "mp3"}),
            ("stream", "/api/v1/tts/stream", {"text": "這是串流語音的隔離驗收。"}),
        ):
            payload.update({"project_id": PROJECT, "provider": "edge-tts", "voice": "zh-TW-HsiaoChenNeural"})
            started = time.perf_counter()
            body = bytearray()
            first_byte = None
            with client.stream("POST", route, headers=headers, json=payload) as response:
                metadata = {"scenario": name, "http_status": response.status_code, "content_type": response.headers.get("content-type"), "provider": response.headers.get("x-tts-provider")}
                if response.status_code != 200:
                    metadata["error"] = response.read().decode("utf-8", errors="replace")[:1000]
                    results.append(metadata)
                    print(json.dumps(metadata, ensure_ascii=False), flush=True)
                    continue
                for chunk in response.iter_bytes():
                    if chunk:
                        if first_byte is None:
                            first_byte = time.perf_counter() - started
                        body.extend(chunk)
            path = output / f"{name}.audio"
            path.write_bytes(body)
            decoded = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"], capture_output=True, check=True)
            assert len(body) > 0 and len(decoded.stdout) > 0
            metadata.update({"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "first_byte_seconds": first_byte, "elapsed_seconds": time.perf_counter() - started, "decoded_pcm_bytes": len(decoded.stdout), "decoded_seconds_16k_mono": len(decoded.stdout) / 32000})
            results.append(metadata)
            print(json.dumps(metadata, ensure_ascii=False), flush=True)
    (output / "voice.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    assert len(results) == 2 and all(result["http_status"] == 200 and result.get("decoded_pcm_bytes", 0) > 0 for result in results), results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:18889")
    parser.add_argument("--output", type=Path, default=Path("/tmp/worker-split-voice"))
    args = parser.parse_args()
    run(args.base, args.output)
