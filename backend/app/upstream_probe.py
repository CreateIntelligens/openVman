"""Background health probes for TTS and batch ASR nodes.

每隔 UPSTREAM_PROBE_INTERVAL_SECONDS 探一次各個設定了網址的節點，掛掉的就在斷路器
裡標成 down，自動備援直接跳過它，故障後的第一個使用者也不必先等一次逾時；探測恢復
就標回 up。探測只在背景跑，永遠不在請求路徑上。只在狀態改變（up→down、down→up）
時記一行 ``upstream_probe``，不記每一次探測。

被管理員或專案指名的引擎照樣會試（service／路由的 explicit 規則），探測只影響自動備援。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

import httpx

from app.config import get_tts_config
from app.upstream_guard import (
    ASR_BREAKER,
    TTS_BREAKER,
    Breaker,
    describe_error,
    host_of,
    knob,
)

logger = logging.getLogger("upstream_attempt")

# 探測判定掛掉後維持幾個週期；探測迴圈停了（例如 task 死掉）也會自己過期，不會永遠跳過。
_DOWN_PERIODS = 3


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    kind: str  # "tts" | "asr"
    node: str
    url: str
    check: Callable[[httpx.AsyncClient], Awaitable[tuple[bool, str]]]

    @property
    def breaker(self) -> Breaker:
        return TTS_BREAKER if self.kind == "tts" else ASR_BREAKER


#: (kind, node) → 上一次探測是否正常；沒有紀錄表示還沒探過。
_last_up: dict[tuple[str, str], bool] = {}


def _health_check(probe, cfg: Any) -> Callable[[httpx.AsyncClient], Awaitable[tuple[bool, str]]]:
    """Wrap a health_payloads probe: up only when it reports ``ready``."""

    async def check(client: httpx.AsyncClient) -> tuple[bool, str]:
        result: dict[str, Any] = await probe(client, cfg)
        status = str(result.get("status", "unknown"))
        if status == "ready":
            return True, ""
        return False, f"{status}: {result.get('error', '')}".rstrip(": ")

    return check


def _reachable_check(url: str) -> Callable[[httpx.AsyncClient], Awaitable[tuple[bool, str]]]:
    """Liveness only: any HTTP answer below 500 counts as up.

    批次 ASR 節點與 Gemini Console 沒有我們確認過的 health 格式；打 ``/health``，
    回 404 也代表服務有在聽，連不上、逾時或 5xx 才算掛。
    """

    async def check(client: httpx.AsyncClient) -> tuple[bool, str]:
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            return False, describe_error(exc)
        if response.status_code >= 500:
            return False, f"HTTP {response.status_code}"
        return True, ""

    return check


def probe_targets(cfg: Any = None) -> list[ProbeTarget]:
    """Every configured TTS and batch ASR node (not Edge, OpenAI or Gemini cloud APIs)."""
    from app import health_payloads as health

    cfg = cfg or get_tts_config()
    targets: list[ProbeTarget] = []

    def url_of(name: str) -> str:
        value = getattr(cfg, name, "") or ""
        return value.strip() if isinstance(value, str) else ""

    for node, field, probe in (
        ("voxcpm", "tts_voxcpm_url", health.probe_voxcpm_health),
        ("cosyvoice", "tts_cosyvoice_url", health.probe_cosyvoice_health),
        ("indextts", "tts_indextts_url", health.probe_indextts_health),
        ("indextts-nurse", "tts_indextts_nurse_url", health.probe_indextts_nurse_health),
    ):
        if url := url_of(field):
            targets.append(ProbeTarget("tts", node, url, _health_check(probe, cfg)))
    if url := url_of("tts_gemini_url"):
        targets.append(ProbeTarget(
            "tts", "gemini-tts", url, _reachable_check(f"{url.rstrip('/')}/health"),
        ))
    for node, field in (
        ("breeze", "asr_breeze_url"),
        ("r2t2", "asr_r2t2_url"),
        ("r2t2-dev", "asr_r2t2_dev_url"),
        ("sensevoice", "asr_sensevoice_url"),
    ):
        if url := url_of(field):
            targets.append(ProbeTarget(
                "asr", node, url, _reachable_check(f"{url.rstrip('/')}/health"),
            ))
    return targets


def _log_transition(target: ProbeTarget, up: bool, elapsed_ms: float, error: str) -> None:
    entry = {
        "event": "upstream_probe",
        "kind": target.kind,
        "node": target.node,
        "host": host_of(target.url),
        "state": "up" if up else "down",
        "elapsed_ms": round(elapsed_ms),
    }
    if error:
        entry["error"] = error
    logger.log(
        logging.INFO if up else logging.WARNING,
        json.dumps(entry, ensure_ascii=False),
    )


async def _probe(client: httpx.AsyncClient, target: ProbeTarget, timeout: float, down_for: float) -> bool:
    started = monotonic()
    try:
        async with asyncio.timeout(timeout):
            up, error = await target.check(client)
    except TimeoutError:
        up, error = False, f"no answer in {timeout:.1f}s"
    except Exception as exc:  # noqa: BLE001 - 探測本身出錯也當成掛掉，不讓迴圈停下
        up, error = False, describe_error(exc)
    elapsed_ms = (monotonic() - started) * 1000

    if up:
        lifted = target.breaker.mark_up(target.node)
        if target.kind == "asr" and lifted:
            # 批次 ASR 的連線失敗冷卻記在自己的表上；連得上了就一起解除。
            from app.gateway import ingestion_audio

            ingestion_audio._unreachable_until.pop(target.node, None)
    else:
        target.breaker.mark_down(target.node, down_for, reason=f"probe: {error}")

    key = (target.kind, target.node)
    previous = _last_up.get(key)
    _last_up[key] = up
    # 第一次探到正常不記（啟動時每台都會是 up），掛掉一定記。
    if (previous is not None and previous != up) or (previous is None and not up):
        _log_transition(target, up, elapsed_ms, error)
    return up


async def probe_once(client: httpx.AsyncClient, cfg: Any = None) -> dict[str, bool]:
    """Probe every configured node once; ``{"kind:node": up}``."""
    cfg = cfg or get_tts_config()
    interval = knob(cfg, "upstream_probe_interval_seconds") or 10.0
    timeout = knob(cfg, "upstream_probe_timeout_seconds")
    targets = probe_targets(cfg)
    results = await asyncio.gather(*(
        _probe(client, target, timeout, interval * _DOWN_PERIODS) for target in targets
    ))
    return {f"{t.kind}:{t.node}": up for t, up in zip(targets, results)}


async def run_upstream_probe_loop(interval: float) -> None:
    """Probe forever every ``interval`` seconds; started by lifecycle.lifespan."""
    timeout = knob(get_tts_config(), "upstream_probe_timeout_seconds")
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        while True:
            try:
                await probe_once(client)
            except Exception as exc:  # noqa: BLE001 - 探測壞掉不能拖垮 backend
                logging.getLogger("backend").warning("upstream probe failed: %s", describe_error(exc))
            await asyncio.sleep(interval)


def reset_probe_state() -> None:
    _last_up.clear()
