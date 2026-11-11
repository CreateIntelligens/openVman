"""Publish isolated integration pages and additive runtime assets on existing nginx."""

import gzip
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "avatar-pipeline"))
from pipeline.render_data import render_data

sample = ROOT / "scripts/experiments/avatar-renderer-next/assets"
frames = json.loads((sample / "character/json_data_151.json").read_text())
template = json.loads((ROOT / "avatar-pipeline/assets/face_template.json").read_text())
portable = render_data(
    [f[:434] for f in frames], [f[434:438] for f in frames], template, 720, 1280
)
files = {}
for path in (ROOT / "frontend/app/public/avatar-engine").rglob("*"):
    if path.is_file():
        files[
            "avatar-engine/"
            + str(path.relative_to(ROOT / "frontend/app/public/avatar-engine"))
        ] = path.read_bytes()
for path in (ROOT / "frontend/app/dist/assets").glob("*"):
    if path.is_file():
        files["assets/" + path.name] = path.read_bytes()
prefix = "experiments/avatar-integration/"
files[prefix + "index.html"] = (ROOT / "frontend/app/dist/index.html").read_bytes()
files[prefix + "openvman-avatar-sdk.js"] = (
    ROOT / "frontend/avatar-sdk/dist/openvman-avatar-sdk.js"
).read_bytes()
files[prefix + "sample/render_data.json.gz"] = gzip.compress(
    json.dumps(portable, allow_nan=False).encode()
)
files[prefix + "sample/01.webm"] = (sample / "character/portrait.webm").read_bytes()
files[prefix + "speech.wav"] = (sample / "speech.wav").read_bytes()
files[prefix + "engine.html"] = (
    ROOT / "scripts/experiments/avatar-renderer-next/integration-preview.html"
).read_bytes()
files[
    prefix + "sdk.html"
] = b"""<!doctype html><html><meta charset="utf-8"><link rel="icon" href="data:,"><body>
<script src="./openvman-avatar-sdk.js"></script></body></html>"""
payload = io.BytesIO()
with tarfile.open(fileobj=payload, mode="w") as archive:
    for name, data in files.items():
        entry = tarfile.TarInfo(name)
        entry.size = len(data)
        entry.mode = 0o644
        archive.addfile(entry, io.BytesIO(data))
subprocess.run(
    [
        "docker",
        "exec",
        "-i",
        "openvman-avatar-1",
        "tar",
        "xf",
        "-",
        "-C",
        "/usr/share/nginx/html",
    ],
    input=payload.getvalue(),
    check=True,
)
print("Preview published:", len(files), "files")
