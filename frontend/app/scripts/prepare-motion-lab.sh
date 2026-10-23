#!/usr/bin/env bash
set -euo pipefail

# File reads/writes and transcoding all happen inside the existing backend.
# Only an additional lab rendition is installed; the registered bundle stays intact.
docker compose exec -T backend python - <<'PY'
import json
import os
from pathlib import Path
import subprocess
import tempfile

import cv2

root = Path('/data/avatar/0624')
source = root / '01.webm'
target = root / 'motion-lab.webm'

def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,r_frame_rate,nb_read_frames',
        '-of', 'json', str(path),
    ]))['streams'][0]

before = probe(source)
if before['r_frame_rate'] != '25/1':
    raise RuntimeError('The lab expects the existing 25 fps bundle')

def markers(path):
    video = cv2.VideoCapture(str(path))
    levels = []
    try:
        while True:
            ok, frame = video.read()
            if not ok:
                return levels
            levels.append(round(float(frame[:2, -2:].mean()) / 40))
    finally:
        video.release()

with tempfile.TemporaryDirectory(prefix='openvman-motion-') as temporary:
    output = Path(temporary) / 'motion-lab.webm'
    subprocess.run([
        'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
        '-i', str(source), '-map', '0:v:0', '-an', '-c:v', 'libvpx-vp9',
        '-b:v', '0', '-crf', '20', '-g', '1', '-auto-alt-ref', '0',
        '-deadline', 'realtime', '-cpu-used', '4', '-threads', '2',
        '-row-mt', '1', str(output),
    ], check=True)
    after = probe(output)
    if before != after:
        raise RuntimeError(f'Timeline/dimensions changed: {before} -> {after}')
    if markers(source) != markers(output):
        raise RuntimeError('Re-encoding changed the frame synchronization markers')
    # The same volume may not share /tmp's filesystem; copy inside the
    # container, then atomically publish after validation.
    pending = target.with_suffix('.pending.webm')
    pending.write_bytes(output.read_bytes())
    os.replace(pending, target)
print(json.dumps({'file': str(target), 'bytes': target.stat().st_size, **after}))
PY
