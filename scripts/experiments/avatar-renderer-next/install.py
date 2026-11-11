"""Build a static experiment from locked dependencies; install only its own directory."""

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
TARGET = "/usr/share/nginx/html/experiments/avatar-renderer-next"


def package():
    files = {}
    for name in [
        "index.html",
        "main.mjs",
        "frame-player.mjs",
        "character-adapter.mjs",
        "renderer.mjs",
    ]:
        files[name] = (ROOT / name).read_bytes()
    for directory in ["inference", "assets"]:
        for path in (ROOT / directory).rglob("*"):
            if path.is_file():
                files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    dist = ROOT / "node_modules/onnxruntime-web/dist"
    for name in [
        "ort.all.min.js",
        "ort-wasm-simd-threaded.mjs",
        "ort-wasm-simd-threaded.wasm",
        "ort-wasm-simd-threaded.jsep.mjs",
        "ort-wasm-simd-threaded.jsep.wasm",
    ]:
        files[f"inference/{name}"] = (dist / name).read_bytes()
    for path in (ROOT / "licenses").iterdir():
        files[f"licenses/{path.name}"] = path.read_bytes()
    files["PROVENANCE.md"] = (ROOT / "PROVENANCE.md").read_bytes()
    manifest = {
        name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in sorted(files.items())
    }
    files["deployment-manifest.json"] = json.dumps(manifest, indent=2).encode()
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    return output.getvalue(), manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="openvman-avatar-1")
    args = parser.parse_args()
    payload, manifest = package()
    staging = f"{TARGET}.next-{uuid4().hex}"
    # Nginx's shipped MIME table omits module scripts. This adds a type, not a route.
    subprocess.run(
        [
            "docker",
            "exec",
            args.container,
            "sh",
            "-c",
            "sed -i 's/application\\/javascript *js;/application\\/javascript js mjs;/' /etc/nginx/mime.types",
        ],
        check=True,
    )
    subprocess.run(
        ["docker", "exec", args.container, "mkdir", "-p", staging], check=True
    )
    subprocess.run(
        ["docker", "exec", "-i", args.container, "tar", "xz", "-C", staging],
        input=payload,
        check=True,
    )
    for name, identity in manifest.items():
        actual = subprocess.check_output(
            ["docker", "exec", args.container, "sha256sum", f"{staging}/{name}"],
            text=True,
        ).split()[0]
        if actual != identity["sha256"]:
            raise RuntimeError(f"Deployment mismatch: {name}")
    backup = f"{TARGET}.previous-{uuid4().hex}"
    existed = (
        subprocess.run(
            ["docker", "exec", args.container, "test", "-d", TARGET], check=False
        ).returncode
        == 0
    )
    if existed:
        subprocess.run(
            ["docker", "exec", args.container, "mv", TARGET, backup], check=True
        )
    try:
        subprocess.run(
            ["docker", "exec", args.container, "mv", staging, TARGET], check=True
        )
    except subprocess.CalledProcessError:
        if existed:
            subprocess.run(
                ["docker", "exec", args.container, "mv", backup, TARGET], check=True
            )
        raise
    if existed:
        subprocess.run(
            ["docker", "exec", args.container, "rm", "-rf", backup], check=True
        )
    subprocess.run(["docker", "exec", args.container, "nginx", "-t"], check=True)
    subprocess.run(
        ["docker", "exec", args.container, "nginx", "-s", "reload"], check=True
    )
    print(json.dumps({"target": TARGET, "verifiedFiles": len(manifest)}, indent=2))


if __name__ == "__main__":
    main()
