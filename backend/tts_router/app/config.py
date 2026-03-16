"""TTS router configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class TTSRouterConfig:
    """Immutable TTS router settings loaded from environment."""

    # --- Self-hosted nodes (Edge-TTS) ---
    tts_primary_node: str = ""
    tts_secondary_node: str = ""

    # --- Index TTS ---
    tts_index_url: str = ""
    tts_index_character: str = "hayley"

    # --- AWS Polly ---
    tts_aws_enabled: bool = False
    tts_aws_region: str = "ap-northeast-1"
    tts_aws_access_key_id: str = ""
    tts_aws_secret_access_key: str = ""
    tts_aws_polly_voice_id: str = "Zhiyu"
    tts_aws_polly_engine: str = "neural"
    tts_aws_output_format: str = "pcm"
    tts_aws_sample_rate: int = 24000

    # --- Node health policy ---
    node_failure_threshold: int = 2
    node_cooldown_seconds: float = 30.0
    node_score_penalty: int = 50
    node_timeout_ms: float = 10_000

    # --- GCP Cloud TTS ---
    tts_gcp_enabled: bool = False
    tts_gcp_project_id: str = ""
    tts_gcp_credentials_json: str = ""
    tts_gcp_voice_name: str = "cmn-TW-Standard-A"
    tts_gcp_audio_encoding: str = "LINEAR16"
    tts_gcp_sample_rate: int = 24000


def _bool_env(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes")


@lru_cache(maxsize=1)
def get_tts_config() -> TTSRouterConfig:
    """Build config from environment variables (cached)."""
    return TTSRouterConfig(
        tts_primary_node=os.environ.get("TTS_PRIMARY_NODE", ""),
        tts_secondary_node=os.environ.get("TTS_SECONDARY_NODE", ""),
        tts_index_url=os.environ.get("TTS_INDEX_URL", ""),
        tts_index_character=os.environ.get("TTS_INDEX_CHARACTER", "hayley"),
        node_failure_threshold=int(os.environ.get("NODE_FAILURE_THRESHOLD", "2")),
        node_cooldown_seconds=float(os.environ.get("NODE_COOLDOWN_SECONDS", "30.0")),
        node_score_penalty=int(os.environ.get("NODE_SCORE_PENALTY", "50")),
        node_timeout_ms=float(os.environ.get("NODE_TIMEOUT_MS", "10000")),
        tts_aws_enabled=_bool_env("TTS_AWS_ENABLED"),
        tts_aws_region=os.environ.get("TTS_AWS_REGION", "ap-northeast-1"),
        tts_aws_access_key_id=os.environ.get("TTS_AWS_ACCESS_KEY_ID", ""),
        tts_aws_secret_access_key=os.environ.get("TTS_AWS_SECRET_ACCESS_KEY", ""),
        tts_aws_polly_voice_id=os.environ.get("TTS_AWS_POLLY_VOICE_ID", "Zhiyu"),
        tts_aws_polly_engine=os.environ.get("TTS_AWS_POLLY_ENGINE", "neural"),
        tts_aws_output_format=os.environ.get("TTS_AWS_OUTPUT_FORMAT", "pcm"),
        tts_aws_sample_rate=int(os.environ.get("TTS_AWS_SAMPLE_RATE", "24000")),
        tts_gcp_enabled=_bool_env("TTS_GCP_ENABLED"),
        tts_gcp_project_id=os.environ.get("TTS_GCP_PROJECT_ID", ""),
        tts_gcp_credentials_json=os.environ.get("TTS_GCP_CREDENTIALS_JSON", ""),
        tts_gcp_voice_name=os.environ.get("TTS_GCP_VOICE_NAME", "cmn-TW-Standard-A"),
        tts_gcp_audio_encoding=os.environ.get("TTS_GCP_AUDIO_ENCODING", "LINEAR16"),
        tts_gcp_sample_rate=int(os.environ.get("TTS_GCP_SAMPLE_RATE", "24000")),
    )
