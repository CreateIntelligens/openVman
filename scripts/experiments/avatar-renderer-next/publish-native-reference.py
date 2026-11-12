"""Publish the explicitly requested original engine reference separately."""

import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--container", default="openvman-avatar-1")
    parser.add_argument("--character", nargs=2, action="append", default=[],
                        metavar=("ID", "COMBINED_DATA"),
                        help="extra character served from <prefix>/<ID>/ with its own package")
    args = parser.parse_args()
    names = ("OpenVmanAvatarRuntime.js", "OpenVmanAvatarRuntime.wasm",
             "combined_data.json.gz", "reference.mjs")
    files = {name: (args.directory / name).read_bytes() for name in names}
    # nginx's stock MIME map covers .js but not .mjs after a container rebuild.
    # The bundle remains an ES module through the page's type="module" script.
    files["reference.js"] = files.pop("reference.mjs")
    files["index.html"] = Path(__file__).with_name("native-reference.html").read_bytes()
    identity = json.loads((args.directory / "identity.json").read_text())
    for name in names[:2]:
        if hashlib.sha256(files[name]).hexdigest() != identity[name]["sha256"]:
            raise ValueError(f"Original engine identity changed: {name}")
    files["identity.json"] = json.dumps(identity, indent=2).encode()
    # Each extra character gets the same runtime beside its own package, so the page's
    # relative paths resolve unchanged inside <ID>/.
    shared = {name: data for name, data in files.items() if name != "combined_data.json.gz"}
    for name, combined in args.character:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError(f"Unsafe character id: {name}")
        for path, data in shared.items():
            files[f"{name}/{path}"] = data
        files[f"{name}/combined_data.json.gz"] = Path(combined).read_bytes()
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        for name, data in files.items():
            entry = tarfile.TarInfo("experiments/avatar-native-reference/" + name)
            entry.size = len(data)
            entry.mode = 0o644
            archive.addfile(entry, io.BytesIO(data))
    subprocess.run(["docker", "exec", "-i", args.container, "tar", "xf", "-",
                    "-C", "/usr/share/nginx/html"], input=payload.getvalue(), check=True)
    print("Published isolated original-engine reference:", len(files), "files")


if __name__ == "__main__":
    main()
