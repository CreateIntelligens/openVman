"""Publish the independently generated rig under an isolated nginx directory.

Only additive files below experiments/avatar-own-rig are written. Existing
production assets, frozen candidates, character files and auth stay untouched.
"""

import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render-data", required=True, type=Path)
    parser.add_argument("--video", type=Path)
    parser.add_argument("--container", default="openvman-avatar-1")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--comparison-summary", type=Path)
    parser.add_argument("--long-speech", type=Path,
                        help="16 kHz mono WAV behind the page's 30 second button")
    parser.add_argument("--character", nargs=3, action="append", default=[],
                        metavar=("ID", "RENDER_DATA", "VIDEO"),
                        help="extra character for the comparison page's selector")
    args = parser.parse_args()
    sample = ROOT / "scripts/experiments/avatar-renderer-next/assets"
    files = {}
    runtime = ROOT / "frontend/app/public/avatar-engine"
    for name in ("index.mjs", "renderer.mjs", "character-adapter.mjs",
                 "frame-player.mjs", "frame-sync.mjs"):
        source = ROOT / "frontend/shared/avatar-engine" / name
        prepared = runtime / "core" / name
        if not prepared.is_file() or prepared.read_bytes() != source.read_bytes():
            raise RuntimeError(f"Prepared runtime is stale: {name}; run pnpm prepare:avatar")
    for path in runtime.rglob("*"):
        if path.is_file():
            files["runtime/" + path.relative_to(runtime).as_posix()] = path.read_bytes()
    files["sample/render_data.json.gz"] = args.render_data.read_bytes()
    files["sample/01.webm"] = (
        args.video or sample / "character/portrait.webm"
    ).read_bytes()
    files["speech.wav"] = (sample / "speech.wav").read_bytes()
    if args.long_speech:
        files["speech-30s.wav"] = args.long_speech.read_bytes()
    characters = []
    for name, render_data, video in args.character:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError(f"Unsafe character id: {name}")
        files[f"characters/{name}/render_data.json.gz"] = Path(render_data).read_bytes()
        files[f"characters/{name}/01.webm"] = Path(video).read_bytes()
        characters.append(name)
    files["characters/index.json"] = json.dumps(characters).encode()
    page = (ROOT / "scripts/experiments/avatar-renderer-next/integration-preview.html").read_text()
    page = page.replace("/avatar-engine/", "./runtime/")
    page = page.replace("['/static/characters/dev-123','./sample']", "['./sample','./sample']")
    page = page.replace("共用人物引擎整合預覽", "自產嘴型資產預覽")
    files["index.html"] = page.encode()
    files["engine.html"] = page.encode()
    files["compare.html"] = (
        ROOT / "scripts/experiments/avatar-renderer-next/compare-own-rig.html"
    ).read_bytes()
    if args.comparison_summary:
        report = args.comparison_summary.read_bytes()
        json.loads(report)
        files["comparison-summary.json"] = report
    sdk = ROOT / "frontend/avatar-sdk/dist/openvman-avatar-sdk.js"
    if sdk.is_file():
        files["openvman-avatar-sdk.js"] = sdk.read_bytes()
        files["sdk.html"] = b'<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><link rel="icon" href="data:,"><body></body></html>'
    manifest = {
        name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in sorted(files.items())
    }
    if any("/rig/" in name or name.endswith(".bin") for name in files):
        raise RuntimeError("Extracted geometry must not enter this delivery")
    files["delivery-manifest.json"] = json.dumps(manifest, indent=2).encode()
    prefix = "experiments/avatar-own-rig/"
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
        for name, data in files.items():
            entry = tarfile.TarInfo(prefix + name)
            entry.size = len(data)
            entry.mode = 0o644
            archive.addfile(entry, io.BytesIO(data))
    subprocess.run(
        ["docker", "exec", "-i", args.container, "tar", "xf", "-",
         "-C", "/usr/share/nginx/html"],
        input=archive_bytes.getvalue(), check=True,
    )
    # This prefix serves only the public demo and its runtime, never character
    # auth routes. CORS permits the real SDK check from a different origin.
    config_path = "/etc/nginx/conf.d/default.conf"
    original = subprocess.check_output(
        ["docker", "exec", args.container, "cat", config_path], text=True,
    )
    location = '''
    location /experiments/avatar-own-rig/ {
        types {
            text/html html;
            text/css css;
            application/javascript js mjs;
            application/wasm wasm;
            application/json json;
            video/webm webm;
            audio/wav wav;
            image/png png;
        }
        add_header Access-Control-Allow-Origin "*" always;
        add_header Cache-Control "no-cache" always;
        gzip on;
        gzip_types application/wasm application/javascript application/octet-stream;
        gzip_min_length 1024;
        try_files $uri $uri/ =404;
        location ~ ^/experiments/avatar-own-rig/runtime/models/ {
            add_header Access-Control-Allow-Origin "*" always;
            add_header Cache-Control "public, max-age=86400" always;
        }
    }
'''
    pattern = r"\s*location /experiments/avatar-own-rig/ \{(?:[^{}]|\{[^{}]*\})*\}"
    if "location /experiments/avatar-own-rig/" in original:
        updated, count = re.subn(pattern, "\n" + location.rstrip(), original)
        if count != 1:
            raise RuntimeError("Ambiguous preview nginx location")
    else:
        at = original.rfind("}")
        if at < 0:
            raise RuntimeError("Preview nginx server block missing")
        updated = original[:at] + location + original[at:]
    if updated != original:
        write = ["docker", "exec", "-i", args.container, "sh", "-c",
                 "cat > /etc/nginx/conf.d/default.conf"]
        subprocess.run(write, input=updated.encode(), check=True)
        try:
            subprocess.run(["docker", "exec", args.container, "nginx", "-t"], check=True)
        except subprocess.CalledProcessError:
            subprocess.run(write, input=original.encode(), check=True)
            raise
        subprocess.run(["docker", "exec", args.container, "nginx", "-s", "reload"], check=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2))
    print(f"Published {len(files)} files below /{prefix}")


if __name__ == "__main__":
    main()
