import json
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.request

def _env_file():
    # worktree 沒有 .env，退回主 checkout（git common dir 的上一層）。
    if os.environ.get("OPENVMAN_ENV_FILE"):
        return pathlib.Path(os.environ["OPENVMAN_ENV_FILE"])
    root = pathlib.Path(__file__).resolve().parents[3]
    if (root / ".env").exists():
        return root / ".env"
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    return (root / common).resolve().parent / ".env"


def _key():
    for line in open(_env_file(), encoding="utf-8"):
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].split("#")[0].strip()
    raise SystemExit("no key")

KEY = _key()
import os
MODEL = os.environ.get("LINT_MODEL", "gemini-3.5-flash-lite")
USAGE = {"in": 0, "out": 0, "calls": 0}

def gen(prompt, *, json_mode=True, model=MODEL, temperature=0.0, retries=4):
    for attempt in range(3):
        try:
            return _gen(prompt, json_mode=json_mode, model=model, temperature=temperature + 0.2 * attempt, retries=retries)
        except json.JSONDecodeError:
            if attempt == 2:
                raise


def _gen(prompt, *, json_mode, model, temperature, retries):
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    for attempt in range(retries):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": KEY})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < retries - 1:
                time.sleep(5 * (attempt + 1)); continue
            raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}")
    um = d.get("usageMetadata", {})
    USAGE["in"] += um.get("promptTokenCount", 0); USAGE["out"] += um.get("candidatesTokenCount", 0); USAGE["calls"] += 1
    text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
    return json.loads(text) if json_mode else text
