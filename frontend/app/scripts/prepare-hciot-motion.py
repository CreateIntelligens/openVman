"""Build the motion lab's separate bundle inside the avatar-pipeline container."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

import cv2
from pipeline.bundle import (
    LANDMARK_SMOOTHING,
    encrypt_inner,
    load_bundle_key,
    load_face_template,
    mouth_crops,
    pose_rows,
    stamp_marker,
)
from pipeline.geometry import smooth_array
from pipeline.landmarks import extract_landmarks


CLIPS = (
    ("idle", "waiting-command.mp4"),
    ("thinking", "thinking.mp4"),
    ("greeting", "idle.mp4"),
    ("bye", "bye.mp4"),
)
FPS = 25
FRAMES_PER_CLIP = 200
WIDTH, HEIGHT = 1080, 1920
TARGET = Path("/data/avatar/0624/motion-lab/hciot-v1")


def emit(stage, **values):
    print(json.dumps({"stage": stage, **values}), flush=True)


def main():
    job = Path(sys.argv[1])
    sources = job / "source"
    hashes = {
        name: hashlib.sha256((sources / name).read_bytes()).hexdigest()
        for _, name in CLIPS
    }
    if TARGET.exists():
        manifest = json.loads((TARGET / "manifest.json").read_text())
        if manifest["sources"] != hashes:
            raise RuntimeError("hciot-v1 已存在但素材不同，請使用新的版本目錄")
        emit("already-installed", path=str(TARGET))
        return
    key = load_bundle_key()
    template = load_face_template()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".hciot-build-", dir=TARGET.parent) as tmp:
        build = Path(tmp)
        output = build / "bundle"
        output.mkdir()
        rows, rects, prepared, segments = [], [], [], {}
        for state, filename in CLIPS:
            emit("prepare", clip=filename)
            video = build / filename
            subprocess.run([
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-y", "-i", str(sources / filename), "-map", "0:v:0",
                "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}",
                "-frames:v", str(FRAMES_PER_CLIP), "-an", "-c:v", "libx264",
                "-preset", "fast", "-crf", "18", "-threads", "2",
                "-pix_fmt", "yuv420p", str(video),
            ], check=True)
            emit("landmarks", clip=filename)
            points = extract_landmarks(video)
            if len(points) != FRAMES_PER_CLIP:
                raise RuntimeError(f"{filename} 並非預期的 200 幀")
            # Smooth each action independently; neighboring clips must not
            # pull the mouth/crop geometry across an edit boundary.
            points = smooth_array(
                points.reshape(len(points), -1), LANDMARK_SMOOTHING,
            ).reshape(len(points), -1, 3)
            crop = mouth_crops(points, WIDTH, HEIGHT)
            start = len(rows) / FPS
            rows.extend(pose_rows(points, crop, template))
            rects.extend(crop.tolist())
            segments[state] = {"start": start, "end": len(rows) / FPS}
            prepared.append(video)

        target_video = output / "01.webm"
        emit("encode", frames=len(rows))
        command = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{WIDTH}x{HEIGHT}",
            "-r", str(FPS), "-i", "-", "-an", "-c:v", "libvpx-vp9",
            "-b:v", "0", "-crf", "20", "-g", str(FRAMES_PER_CLIP),
            "-auto-alt-ref", "0", "-deadline", "realtime", "-cpu-used", "4",
            "-threads", "2", "-row-mt", "1", "-pix_fmt", "yuv420p",
            "-force_key_frames", "0,8,16,24",
            str(target_video),
        ]
        with tempfile.TemporaryFile() as error_log:
            encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=error_log)
            index = 0
            try:
                for video in prepared:
                    reader = cv2.VideoCapture(str(video))
                    try:
                        while True:
                            ok, frame = reader.read()
                            if not ok:
                                break
                            stamp_marker(frame, index)
                            encoder.stdin.write(frame.tobytes())
                            index += 1
                    finally:
                        reader.release()
            finally:
                encoder.stdin.close()
                encoder.wait()
            if encoder.returncode:
                error_log.seek(0)
                raise RuntimeError(error_log.read().decode()[-1000:])
        if index != len(rows):
            raise RuntimeError("影片與逐幀資料數量不符")

        emit("validate")
        reader = cv2.VideoCapture(str(target_video))
        decoded = 0
        try:
            while True:
                ok, frame = reader.read()
                if not ok:
                    break
                marker = round(float(frame[:2, -2:].mean()) / 40)
                if marker != decoded % 7:
                    raise RuntimeError(f"第 {decoded} 幀的同步標記不正確")
                decoded += 1
        finally:
            reader.release()
        if decoded != len(rows):
            raise RuntimeError("VP9 解碼幀數與資料不符")
        frames = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_frames", "-show_entries", "frame=key_frame",
            "-of", "json", str(target_video),
        ]))["frames"]
        if any(not frames[index]["key_frame"] for index in range(0, decoded, FRAMES_PER_CLIP)):
            raise RuntimeError("動作起點缺少關鍵幀")
        inner = {
            "uid": f"vman_{uuid.uuid4()}", "frame_num": len(rows),
            "face3D_obj": template, "rect": rects, "reverse_option": 0,
        }
        payload = {
            "combined_data": encrypt_inner(
                key, json.dumps(inner, separators=(",", ":")).encode(),
            ),
            "json_data": rows,
        }
        with gzip.open(output / "combined_data.json.gz", "wt") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        manifest = {
            "id": "hciot-v1", "fps": FPS, "frameCount": len(rows),
            "width": WIDTH, "height": HEIGHT, "sources": hashes,
            "segments": segments, "audio": "removed-silent-source-tracks",
        }
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
        os.replace(output, TARGET)
    emit("installed", path=str(TARGET), frames=decoded,
         videoBytes=(TARGET / "01.webm").stat().st_size)


if __name__ == "__main__":
    main()
