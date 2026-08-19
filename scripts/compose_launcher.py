#!/usr/bin/env python3
"""Thin Compose launcher that infers GPU profiles, injects consumer routing variables, and invokes docker compose."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import NamedTuple
from urllib.parse import urlparse, urlunparse


class ResolvedRouting(NamedTuple):
    embedding_mode: str
    vlm_mode: str
    indextts_mode: str
    final_profiles: list[str]
    injected_env: dict[str, str]
    warnings: list[str]


def parse_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.is_file():
        return {}
    res = {}
    with env_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            res[k.strip()] = v.strip().strip("'\"")
    return res


def sanitize_url(raw_url: str) -> str:
    """Sanitize URL by stripping query parameters and passwords."""
    if not raw_url:
        return ""
    try:
        parsed = urlparse(raw_url)
        netloc = parsed.netloc
        if "@" in netloc:
            auth, _, host = netloc.partition("@")
            user = auth.split(":")[0] if ":" in auth else auth
            netloc = f"{user}:***@{host}" if user else host
        sanitized = urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
        return sanitized.rstrip("/")
    except Exception:
        return raw_url.split("?")[0]


def resolve_routing(env: dict[str, str]) -> ResolvedRouting:
    raw_profiles = env.get("COMPOSE_PROFILES", "")
    explicit_profiles = [p.strip() for p in raw_profiles.split(",") if p.strip()]
    final_profiles = list(explicit_profiles)
    injected_env: dict[str, str] = {}
    warnings: list[str] = []

    emb_url = env.get("EMBEDDING_SERVICE_URL", "").strip()
    vlm_url = env.get("VISION_LLM_BASE_URL", "").strip()
    tts_url = env.get("TTS_INDEXTTS_URL", "").strip()

    # 1. Embedding resolution (required)
    if emb_url:
        embedding_mode = f"External ({sanitize_url(emb_url)})"
        if "embedding" in explicit_profiles:
            warnings.append("Both EMBEDDING_SERVICE_URL and 'embedding' profile are configured; external URL takes precedence.")
    else:
        if "embedding" not in final_profiles:
            final_profiles.append("embedding")
        injected_env["EMBEDDING_SERVICE_URL"] = "http://embedding:8009"
        embedding_mode = "Local (profile: embedding)"

    # 2. VLM resolution (optional)
    if vlm_url:
        vlm_mode = f"External ({sanitize_url(vlm_url)})"
        if "vlm" in explicit_profiles:
            warnings.append("Both VISION_LLM_BASE_URL and 'vlm' profile are configured; external URL takes precedence.")
    elif "vlm" in explicit_profiles:
        injected_env["VISION_LLM_BASE_URL"] = "http://vlm:8000/v1"
        injected_env["VISION_LLM_API_KEY"] = env.get("VISION_LLM_API_KEY") or "local-vlm"
        injected_env["VISION_LLM_MODEL"] = env.get("VISION_LLM_MODEL") or "openvman-vlm"
        vlm_mode = "Local (profile: vlm)"
    else:
        vlm_mode = "Disabled (optional)"

    # 3. IndexTTS resolution (optional)
    if tts_url:
        indextts_mode = f"External ({sanitize_url(tts_url)})"
        if "indextts" in explicit_profiles:
            warnings.append("Both TTS_INDEXTTS_URL and 'indextts' profile are configured; external URL takes precedence.")
    elif "indextts" in explicit_profiles:
        injected_env["TTS_INDEXTTS_URL"] = "http://index-tts-vllm:8011"
        indextts_mode = "Local (profile: indextts)"
    else:
        indextts_mode = "Disabled (optional)"

    return ResolvedRouting(
        embedding_mode=embedding_mode,
        vlm_mode=vlm_mode,
        indextts_mode=indextts_mode,
        final_profiles=final_profiles,
        injected_env=injected_env,
        warnings=warnings,
    )


def print_routing(routing: ResolvedRouting) -> None:
    print("=== OpenVman Compose GPU Routing ===")
    print(f"  Embedding : {routing.embedding_mode}")
    print(f"  VLM       : {routing.vlm_mode}")
    print(f"  IndexTTS  : {routing.indextts_mode}")
    print(f"  Profiles  : {','.join(routing.final_profiles) if routing.final_profiles else '(none)'}")
    if routing.warnings:
        for w in routing.warnings:
            print(f"  [WARN] {w}")
    print("====================================")


def main(args: list[str]) -> None:
    root = Path(__file__).resolve().parents[1]
    env_file = root / ".env"
    env_vars = parse_env_file(env_file)
    # Merge host environment with .env values (host takes precedence)
    merged_env = {**env_vars, **os.environ}

    routing = resolve_routing(merged_env)
    print_routing(routing)

    # Set resolved COMPOSE_PROFILES and injected environment variables
    os.environ["COMPOSE_PROFILES"] = ",".join(routing.final_profiles)
    for k, v in routing.injected_env.items():
        if k not in os.environ:
            os.environ[k] = v

    # Execute docker compose
    cmd = ["docker", "compose"] + args
    try:
        os.execvp("docker", cmd)
    except Exception as exc:
        print(f"Failed to exec docker compose: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
