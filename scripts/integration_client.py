#!/usr/bin/env python3
"""Discover account capabilities or run one ASR → chat → TTS turn."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import ssl
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)


class IntegrationError(Exception):
    """A request or response cannot safely continue the integration flow."""


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the account credential to a redirected origin.
        return None


class Client:
    def __init__(self, base_url: str, api_key: str, ca_file=None):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise IntegrationError("base URL 必須是無帳密、query 或 fragment 的 HTTP(S) 網址")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        context = ssl.create_default_context(cafile=ca_file)
        self.opener = build_opener(
            RejectRedirects(), HTTPSHandler(context=context)
        )

    def emit(self, text):
        print(str(text).replace(self.api_key, "[REDACTED]"))

    def request(self, path, *, body=None, content_type=None):
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if content_type:
            headers["Content-Type"] = content_type
        request = Request(self.base_url + path, data=body, headers=headers)
        try:
            with self.opener.open(request, timeout=120) as response:
                return response.read(), response.headers
        except HTTPError as exc:
            # Upstream error bodies can echo credentials or private request data.
            raise IntegrationError(f"{path}: HTTP {exc.code}") from None
        except (URLError, TimeoutError):
            raise IntegrationError(f"{path}: 連線失敗或逾時（請檢查網址、TLS 及服務）") from None

    def json_request(self, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        raw, _ = self.request(
            path, body=body,
            content_type="application/json" if body is not None else None,
        )
        return parse_object(raw)

    def transcribe(self, audio, project_id, provider=None):
        fields = {"project_id": project_id}
        if provider:
            fields["provider"] = provider
        body, content_type = multipart(audio, fields)
        raw, _ = self.request(
            "/api/v1/asr/transcribe", body=body, content_type=content_type
        )
        result = parse_object(raw)
        text = result.get("text")
        if (
            not result.get("provider")
            or not isinstance(text, str)
            or not text.strip()
            or text.strip() == "（音訊轉錄失敗）"
        ):
            raise IntegrationError("ASR 未產生有效結果；停止呼叫 Chat 與 TTS")
        return result


def parse_object(raw):
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise IntegrationError("服務未回傳有效 JSON") from None
    if not isinstance(result, dict):
        raise IntegrationError("服務回應必須為 JSON object")
    return result


def multipart(audio: Path, fields: dict[str, str]):
    boundary = "openvman-" + uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
            f"\r\n\r\n{value}\r\n".encode()
        )
    # A fixed filename avoids putting user-controlled headers in multipart data.
    mime = mimetypes.guess_type(audio.name)[0] or "application/octet-stream"
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="audio{audio.suffix if audio.suffix.isascii() and audio.suffix[1:].isalnum() else ""}"'
        f"\r\nContent-Type: {mime}\r\n\r\n".encode()
    )
    parts.extend((audio.read_bytes(), f"\r\n--{boundary}--\r\n".encode()))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def select_project(capabilities, requested):
    projects = capabilities.get("projects", [])
    allowed = {
        project.get("project_id")
        for project in projects if isinstance(project, dict)
    }
    selected = requested or capabilities.get("defaults", {}).get("project_id")
    if not selected or selected not in allowed:
        raise IntegrationError("請用 --project-id 指定 capabilities.projects 中的 project_id")
    return selected


def save_audio(raw, content_type, output: Path):
    mime = content_type.partition(";")[0].strip().lower()
    extensions = {
        "audio/wav": ".wav", "audio/x-wav": ".wav",
        "audio/wave": ".wav", "audio/vnd.wave": ".wav",
        "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
        "audio/l16": ".pcm", "audio/pcm": ".pcm",
    }
    if not raw:
        raise IntegrationError("TTS 回傳空音訊")
    if mime not in extensions:
        raise IntegrationError("TTS 回傳未支援的 Content-Type，未寫入音訊")
    destination = output.with_suffix(extensions[mime])
    with destination.open("xb") as handle:
        handle.write(raw)
    return destination, mime in {"audio/l16", "audio/pcm"}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--base-url", required=True,
                        help="公開入口，含部署子路徑，例如 https://host/openvman")
    result.add_argument("--discover-only", action="store_true",
                        help="只列能力，不辨識、不建立對話、不合成")
    result.add_argument("--project-id", help="能力清單中的 opaque project_id")
    result.add_argument("--audio", type=Path, help="要上傳辨識的音檔")
    result.add_argument("--asr-provider", help="此請求的 batch ASR 引擎")
    result.add_argument("--tts-provider", help="此請求的 TTS provider")
    result.add_argument("--voice", help="已授權 voice_id；省略使用帳號預設")
    result.add_argument("--output", type=Path, default=Path("reply"),
                        help="輸出路徑；副檔名依 Content-Type 決定，不覆蓋既有檔案")
    result.add_argument("--ca-file", help="內部 CA PEM；仍驗證 TLS 憑證與主機名")
    return result


def run(args, client):
    capabilities = client.json_request("/api/v1/me/capabilities")
    if capabilities.get("schema_version") != 1:
        raise IntegrationError("不支援的 capabilities schema_version")
    if args.discover_only:
        client.emit(json.dumps(capabilities, ensure_ascii=False, indent=2))
        return
    project_id = select_project(capabilities, args.project_id)
    if args.asr_provider:
        batch = capabilities.get("asr", {}).get("batch", [])
        if not any(
            item.get("id") == args.asr_provider
            and item.get("configured") is True
            for item in batch
        ):
            raise IntegrationError("指定 ASR 不在已授權且已設定的 batch 清單")
    asr = client.transcribe(args.audio, project_id, args.asr_provider)
    session_id = "integration-" + uuid.uuid4().hex
    language = asr.get("language") or ""
    chat = client.json_request("/api/v1/chat", {
        "message": asr["text"], "project_id": project_id,
        "session_id": session_id,
        "metadata": {"speech_language": language},
    })
    reply = chat.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        raise IntegrationError("Chat 未回傳有效 reply；停止 TTS")
    payload = {
        "text": reply, "project_id": project_id,
        "speech_language": language,
    }
    if args.tts_provider:
        payload["provider"] = args.tts_provider
    if args.voice:
        payload["voice"] = args.voice
    raw, headers = client.request(
        "/api/v1/tts/stream", body=json.dumps(payload).encode(),
        content_type="application/json",
    )
    content_type = headers.get("Content-Type", "")
    destination, is_pcm = save_audio(raw, content_type, args.output)
    client.emit(f"session_id: {session_id}")
    client.emit(f"ASR ({asr['provider']}): {asr['text']}")
    client.emit(f"Chat: {reply}")
    client.emit(f"音訊: {destination} ({content_type})")
    if is_pcm:
        client.emit("raw PCM 無檔頭；依 Content-Type 的 rate/channels 與供應商位元序設定解碼。")
        client.emit("目前 Gemini 串流為 24000 Hz、單聲道、16-bit little-endian。")


def main(argv=None):
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if not args.discover_only and args.audio is None:
        argument_parser.error("語音流程需要 --audio；只探索請加 --discover-only")
    api_key = os.environ.get("OPENVMAN_API_KEY", "").strip()
    if not api_key:
        argument_parser.error("請在環境設定 OPENVMAN_API_KEY")
    try:
        run(args, Client(args.base_url, api_key, args.ca_file))
    except (IntegrationError, OSError, ValueError) as exc:
        # Redact even if a remote service echoed the credential into an error.
        print(f"錯誤: {str(exc).replace(api_key, '[REDACTED]')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
