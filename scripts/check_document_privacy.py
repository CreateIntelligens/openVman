#!/usr/bin/env python3
"""Check owned documentation for deployment identifiers without echoing values."""

import argparse
import ipaddress
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit


EXCLUDED = {
    ".git", ".remember", ".worktree", ".worktrees", ".venv", "node_modules",
    "vendor", "third_party", "third-party", "data", "runtime", "logs",
    ".hf_cache", "graphify-out",
}
PUBLIC_HOSTS = {
    "github.com", "raw.githubusercontent.com", "huggingface.co", "arxiv.org",
    "doi.org", "modelscope.cn", "pytorch.org", "platform.openai.com",
    "api.openai.com", "developers.openai.com", "api.typesafe.ai", "nen.com.tw",
    "www.evak-pumps.com", "docs.d-id.com", "www.d-id.com", "docs.liveavatar.com",
    "www.w3.org", "learn.microsoft.com", "developer.nvidia.com",
    "www.metahuman.com", "static.www.tencent.com", "openbmb.github.io",
    "pypi.org", "cdn.jsdelivr.net", "registry.npmjs.org", "developers.google.com",
    "ai.google.dev", "ghcr.io", "hub.docker.com", "registry-1.docker.io",
    "www.motc.gov.tw", "www.ntu.edu.tw", "www.cwa.gov.tw",
}
SERVICE_HOSTS = {
    "localhost", "backend", "api", "brain", "admin", "avatar", "nginx",
    "redis", "embedding", "vlm", "index-tts-vllm", "voxcpm-gateway",
    "grafana", "prometheus", "server1", "server2",
}
PUBLIC_EMAILS = {"sales@evak-pumps.com", "privacy@typesafe.ai"}
PRIVATE_NETWORKS = tuple(map(ipaddress.ip_network, (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
)))
RESERVED_NETWORKS = tuple(map(ipaddress.ip_network, (
    "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "127.0.0.0/8",
)))
PATTERNS = {
    "account-id": r"\busr_[a-f0-9]{16,}\b",
    "project-id": r"\b(?:proj|dev|esg)-[a-f0-9]{8,}\b",
    "observation-id": (
        r"\b(?!(?:00000000-0000-0000-0000-000000000000|"
        r"123e4567-e89b-12d3-a456-426614174000|"
        r"550e8400-e29b-41d4-a716-446655440000)\b)"
        r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\b"
    ),
    "account-key": r"\bovk_[a-f0-9]{32}(?:\.[A-Za-z0-9_-]+)?",
    "mac-address": r"\b(?:[a-f0-9]{2}[:-]){5}[a-f0-9]{2}\b",
    "credential": (
        r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{35}|"
        r"AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{36}|"
        r"github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b"
    ),
    "jwt": r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
    "private-key": r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
    "bearer-secret": r"\bBearer\s+[A-Za-z0-9_.-]{32,}\b",
}
COMPILED = {name: re.compile(value, re.I) for name, value in PATTERNS.items()}
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
HOME = re.compile(r"/(?:home|Users)/([^/\s`\"'<>]+)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
URL = re.compile(r"(?:https?|wss?)://[^\s<>`\"'()\[\]{}]+")
USERNAME = re.compile(
    r"[\"']username[\"']\s*[:=]\s*[\"']([^\"'\s]+)|"
    r"(?:^|\s)--(?:username|user)\s+([A-Za-z0-9_.@-]+|\$\w+|<[^>]+>)",
    re.I,
)


def is_document(path):
    p = Path(path)
    if any(part in EXCLUDED for part in p.parts):
        return False
    if p.name.lower().startswith(("license", "copying")):
        return False
    if p.name == "CMakeLists.txt" or (
        p.suffix.lower() == ".txt" and p.name.lower().startswith("requirements")
    ):
        return False
    if p.suffix.lower() in {".md", ".rst", ".adoc", ".txt"}:
        return True
    if p.suffix.lower() == ".html" and p.parts[0] == "examples":
        return True
    return p.suffix.lower() in {".json", ".jsonl", ".csv", ".yaml", ".yml"} and (
        path.startswith("scripts/experiments/")
        or path.startswith("scripts/voice_e2e/cases/")
    )


def reserved_domain(host):
    return any(host == tail or host.endswith("." + tail) for tail in (
        "example", "example.com", "example.net", "example.org", "test",
        "invalid", "localhost",
    ))


def allowed_host(host):
    host = host.lower().rstrip(".;,")
    if (reserved_domain(host) or host in PUBLIC_HOSTS or host in SERVICE_HOSTS
            or host.startswith("your_") or host.startswith("$")):
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_unspecified or address.is_loopback or any(
            address.version == n.version and address in n for n in RESERVED_NETWORKS
        )
    except ValueError:
        return False


def line_categories(line):
    found = {name for name, pattern in COMPILED.items() if pattern.search(line)}
    for match in USERNAME.finditer(line):
        value = match[1] or match[2]
        if not (
            value.startswith(("example-", "<", "$"))
            or value in {"ROOT_USERNAME", "root", "admin", "user"}
        ):
            found.add("literal-username")
    for value in IPV4.findall(line):
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if any(address in n for n in PRIVATE_NETWORKS):
            found.add("private-ip")
        elif not allowed_host(value):
            found.add("real-ip")
    for match in HOME.finditer(line):
        allowed = {"example", "operator"} if match[0].startswith("/home/") else {"example"}
        if match[1] not in allowed:
            found.add("personal-home")
    for match in EMAIL.finditer(line):
        if match[0].lower() not in PUBLIC_EMAILS and not reserved_domain(match[1].lower()):
            found.add("personal-email")
    for match in URL.finditer(line):
        try:
            parsed = urlsplit(match[0].rstrip(".,;:"))
            if parsed.username or parsed.password:
                found.add("url-credential")
            if parsed.hostname and not allowed_host(parsed.hostname):
                found.add("unreviewed-url-host")
        except ValueError:
            found.add("invalid-url")
    return found


def scan(root):
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
         "--exclude-standard"], capture_output=True, check=True,
    )
    findings = []
    paths = sorted(set(result.stdout.decode("utf-8").split("\0")) - {""})
    for path in paths:
        if not is_document(path) or not (root / path).is_file():
            continue
        if (root / path).is_symlink():
            continue
        try:
            lines = (root / path).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            findings.append((path, 1, "unreadable-document"))
            continue
        for number, line in enumerate(lines, 1):
            findings.extend((path, number, category) for category in sorted(line_categories(line)))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        findings = scan(args.root.resolve())
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        print(".:1: scan-error")
        return 2
    for path, number, category in findings:
        print(f"{path}:{number}: {category}")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
