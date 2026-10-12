"""Destination policy for URLs the Brain fetches on the model's behalf."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse


def validate_public_url(raw_url: Any) -> str:
    """Return the URL if it is plain http(s) and resolves only to public hosts.

    Every resolved address is checked, so a hostname that maps to an internal
    address alongside a public one is still rejected.
    """
    url = str(raw_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("無效的網址：只支援 http/https URL")
    if parsed.username or parsed.password:
        raise ValueError("無效的網址：不支援嵌入帳號密碼")
    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ValueError("無法解析該網址的網域") from exc
    if not addresses or any(
        (
            (ip := ipaddress.ip_address(address)).is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
        for address in addresses
    ):
        raise ValueError("不允許讀取內部或特殊網路位址")
    if len(url) > 4096:
        raise ValueError("網址過長")
    return url
