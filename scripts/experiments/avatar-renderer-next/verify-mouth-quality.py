"""Mouth quality evidence through the real page: both engines on the real GPU.

Writes what a person needs to judge the mouth rather than a verdict about it:
same-frame interventions, consecutive live frames, full faces and recordings with
sound. The native column is a reference: its coefficient series is read to report
how closely the two engines agree, and nothing here is fed back into generated
assets. Passing these checks does not establish that it looks natural.
"""

import argparse
import base64
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright


ARGS = ["--no-sandbox", "--use-gl=angle", "--use-angle=gl-egl", "--ignore-gpu-blocklist"]
MOUTH = (305, 265, 120, 78)
FACE = (270, 190, 190, 210)
REST = [-4.172, -2.566, -4.243, -2.737, 1.528, -3.051]

FORCE = """async seconds => {
  await comparison.newer.player.freeze(seconds);
  comparison.native.beginPcm(new Int16Array(16000 * 600));
  window.forced = new Float32Array(12); window.forcedCalls = 0;
  const g = comparison.native.instance.ctx, original = g.uniform1fv.bind(g);
  g.uniform1fv = (location, values, start, count) => {
    if (count === 12 || values.length === 12) { forcedCalls++; return original(location, forced); }
    return original(location, values, ...(start === undefined ? [] : [start, count]));
  };
}"""
SET = """vector => {
  window.forced = new Float32Array(vector);
  const player = comparison.newer.player;
  player.holdControls(vector); player.draw();
}"""
GRAB = """box => [comparison.native.canvas, comparison.newer.canvas].map(source => {
  const c = document.createElement('canvas'); c.width = box[2]; c.height = box[3];
  c.getContext('2d').drawImage(source, box[0], box[1], box[2], box[3], 0, 0, box[2], box[3]);
  return c.toDataURL();
})"""
PLAY = """async ({url, box, face, start, count, stopAfter}) => {
  const {native, newer} = comparison, context = newer.audioContext;
  await newer.prepare();
  const audio = await context.decodeAudioData(await (await fetch(url)).arrayBuffer());
  const pcm = Int16Array.from(audio.getChannelData(0), value => Math.round(value * 32767));
  const canvas = document.createElement('canvas');
  canvas.width = face[2] * 2 + 8; canvas.height = face[3];
  const paint = canvas.getContext('2d'); paint.fillStyle = '#fff';
  const destination = context.createMediaStreamDestination(); newer.output.connect(destination);
  const stream = new MediaStream([...canvas.captureStream(30).getVideoTracks(), ...destination.stream.getAudioTracks()]);
  const chunks = [], recorder = new MediaRecorder(stream, {mimeType: 'video/webm;codecs=vp8,opus'});
  recorder.ondataavailable = event => chunks.push(event.data); recorder.start(100);
  let frameLoop;
  const copy = () => {
    paint.fillRect(0, 0, canvas.width, canvas.height);
    paint.drawImage(native.canvas, face[0], face[1], face[2], face[3], 0, 0, face[2], face[3]);
    paint.drawImage(newer.canvas, face[0], face[1], face[2], face[3], face[2] + 8, 0, face[2], face[3]);
    frameLoop = requestAnimationFrame(copy);
  };
  copy();
  const uniform = {last: null}, g = native.instance.ctx, original = g.uniform1fv.bind(g);
  g.uniform1fv = (location, values, first, length) => {
    if (length === 12) uniform.last = Array.from(values.subarray(first, first + 12));
    else if (values.length === 12) uniform.last = Array.from(values);
    return original(location, values, ...(first === undefined ? [] : [first, length]));
  };
  let audible = null;
  newer.controller.onFirstAudio = ({playbackStartTime}) => {
    if (audible !== null) return;
    audible = playbackStartTime;
    setTimeout(() => native.beginPcm(pcm), Math.max(0, (playbackStartTime - context.currentTime) * 1000 - 8));
  };
  newer.video.currentTime = 0; await newer.video.play();
  const series = [];
  const logger = setInterval(() => {
    const geometry = newer.player.lastGeometry;
    series.push({at: audible === null ? null : context.currentTime - audible, native: uniform.last,
      controls: Array.from(newer.player.controls).slice(0, 6),
      gap: geometry ? geometry.gap / geometry.width : null});
  }, 20);
  const crop = source => {
    const c = document.createElement('canvas'); c.width = box[2]; c.height = box[3];
    c.getContext('2d').drawImage(source, box[0], box[1], box[2], box[3], 0, 0, box[2], box[3]);
    return c.toDataURL();
  };
  const frames = [];
  let next = start, stopped = false, stoppedAt = null;
  const finished = (async () => { await newer.appendPcm(pcm); await newer.finishAudio(); })();
  const capture = () => {
    if (audible !== null) {
      const now = context.currentTime - audible;
      if (now >= next && frames.length < count) {
        frames.push({at: now, images: [crop(native.canvas), crop(newer.canvas)]});
        next += 0.04;
      }
      if (stopAfter !== null && !stopped && now >= stopAfter) {
        stopped = true; stoppedAt = now; newer.stop(); native.stop();
      }
    }
    const stopPending = stopAfter !== null && !stopped;
    if (stopPending || (frames.length < count && !stopped)) requestAnimationFrame(capture);
  };
  requestAnimationFrame(capture);
  await finished;
  clearInterval(logger); native.stop();
  // A stop leaves the player easing shut; give it time, then confirm it reached the source.
  await new Promise(resolve => setTimeout(resolve, 600));
  const settled = {stoppedAt, neutral: newer.player.lastGeometry.neutral, controls: Array.from(newer.player.controls),
    liveSources: newer.controller.liveSources.size, state: newer.state, duration: audio.duration,
    scheduledSeconds: audible === null ? null : context.currentTime - audible};
  cancelAnimationFrame(frameLoop); recorder.stop();
  await new Promise(resolve => { recorder.onstop = resolve; });
  newer.output.disconnect(destination); g.uniform1fv = original;
  const bytes = new Uint8Array(await new Blob(chunks, {type: 'video/webm'}).arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return {webm: btoa(binary), series, frames, settled};
}"""
SOURCE_MATCH = """async () => {
  const {newer} = comparison, player = newer.player, canvas = player.canvas;
  // Hold one frame so both sides of the comparison show the same picture.
  await player.freeze(2);
  player.draw();
  const shown = player.context.getImageData(0, 0, canvas.width, canvas.height).data;
  const c = document.createElement('canvas'); c.width = canvas.width; c.height = canvas.height;
  const x = c.getContext('2d', {willReadFrequently: true}); x.drawImage(player.video, 0, 0, canvas.width, canvas.height);
  const source = x.getImageData(0, 0, canvas.width, canvas.height).data;
  // The 16 pixel corner holds the frame marker, which playback repairs on purpose.
  let different = 0;
  for (let y = 0; y < canvas.height; y++) for (let i = 0; i < canvas.width; i++) {
    if (y < 17 && i >= canvas.width - 17) continue;
    const at = (y * canvas.width + i) * 4;
    if (Math.max(Math.abs(shown[at] - source[at]), Math.abs(shown[at + 1] - source[at + 1]), Math.abs(shown[at + 2] - source[at + 2])) > 2) different++;
  }
  return different;
}"""


def image(data):
    return Image.open(io.BytesIO(base64.b64decode(data.split(";base64,")[1]))).convert("RGB")


def rows_sheet(rows, path, scale=3):
    width, height = rows[0][1][0].size
    sheet = Image.new("RGB", (90 + 2 * width * scale, len(rows) * height * scale), "white")
    draw = ImageDraw.Draw(sheet)
    for row, (label, pair) in enumerate(rows):
        draw.text((4, row * height * scale + 8), label, fill="black")
        for column, picture in enumerate(pair):
            sheet.paste(picture.resize((width * scale, height * scale), Image.LANCZOS),
                        (90 + column * width * scale, row * height * scale))
    sheet.save(path)


def grid_sheet(cells, path, columns=4, scale=2):
    width, height = cells[0][1][0].size
    lines = (len(cells) + columns - 1) // columns
    sheet = Image.new("RGB", ((width * 2 + 6) * scale * columns, (height + 10) * scale * lines), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, pair) in enumerate(cells):
        x, y = (index % columns) * (width * 2 + 6) * scale, (index // columns) * (height + 10) * scale
        draw.text((x + 2, y + 2), label, fill="black")
        for column, picture in enumerate(pair):
            sheet.paste(picture.resize((width * scale, height * scale), Image.LANCZOS),
                        (x + column * width * scale, y + 10 * scale))
    sheet.save(path)


def close_up_drives_both(page):
    """Both columns must keep moving on screen while zoomed, at a desktop column width."""
    page.click("#close-up")
    page.click("#play")
    page.wait_for_function("comparison.native.telemetry.chunks >= 20")
    page.evaluate("""async () => {
      const video = comparison.newer.video; video.pause();
      if (Math.abs(video.currentTime - 2) > .001)
        await new Promise(resolve => { video.addEventListener('seeked', resolve, {once: true}); video.currentTime = 2; });
    }""")
    views = page.evaluate("[...document.querySelectorAll('.view')].map(e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })")
    shots = []
    for _ in range(10):
        page.wait_for_timeout(200)
        shots.append(np.asarray(Image.open(io.BytesIO(page.screenshot())).convert("RGB")).astype(int))
    changed = []
    for left, top, width, height in views:
        crops = [shot[int(top + height * .42):int(top + height * .8), int(left + width * .3):int(left + width * .7)] for shot in shots]
        changed.append(max(int((np.abs(crop - crops[0]).max(axis=2) > 6).sum()) for crop in crops[1:]))
    page.click("#stop")
    return changed


def agreement(series):
    """Correlate the two engines' coefficients at their best small time offset."""
    usable = [row for row in series if row["native"] and any(row["controls"]) and any(row["native"][:6])]
    if len(usable) < 20:
        return {"samples": len(usable)}
    native = np.array([row["native"][:6] for row in usable], float)
    newer = np.array([row["controls"] for row in usable], float)
    best = max(range(-8, 9), key=lambda lag: np.corrcoef(
        native[max(0, lag):len(native) + min(0, lag), 0],
        newer[max(0, -lag):len(newer) + min(0, -lag), 0])[0, 1])
    a, b = native[max(0, best):len(native) + min(0, best)], newer[max(0, -best):len(newer) + min(0, -best)]
    return {
        "samples": len(usable), "bestLagSamples": best, "sampleMs": 20,
        "correlation": [round(float(np.corrcoef(a[:, i], b[:, i])[0, 1]), 3) for i in range(6)],
        "nativeStd": a.std(axis=0).round(2).tolist(), "newerStd": b.std(axis=0).round(2).tolist(),
    }


def speech_run(page, out, name, url, start, count, stop_after=None):
    result = page.evaluate(PLAY, {"url": url, "box": list(MOUTH), "face": list(FACE),
                                  "start": start, "count": count, "stopAfter": stop_after})
    (out / f"{name}.webm").write_bytes(base64.b64decode(result["webm"]))
    if result["frames"]:
        grid_sheet([(f"{row['at']:.2f}s", [image(item) for item in row["images"]])
                    for row in result["frames"]], out / f"{name}-mouth-sequence.png")
    settled = result["settled"]
    assert settled["neutral"], settled
    assert all(value == 0 for value in settled["controls"]), settled
    assert settled["liveSources"] == 0, settled
    differing = page.evaluate(SOURCE_MATCH)
    assert differing == 0, f"{name}: {differing} pixels differ from the source video once idle"
    gaps = np.array([row["gap"] for row in result["series"] if row["gap"] is not None])
    return {
        "settled": settled, "agreement": agreement(result["series"]),
        "gapWidths": {key: round(float(np.percentile(gaps, value)), 3)
                      for key, value in (("p5", 5), ("p50", 50), ("p95", 95), ("max", 100))},
        "sealedFraction": round(float((gaps < 0.03).mean()), 3),
        "sourcePixelsDifferingWhenIdle": differing,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://127.0.0.1:8787/experiments/avatar-own-rig/compare.html")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--calibration", required=True, type=Path,
                        help="mouth-calibration.json, whose sound medians drive the mixed-pose row")
    parser.add_argument("--long-seconds", type=int, default=30)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sounds = json.loads(args.calibration.read_text())["classes"]
    cases = [("silence", REST)]
    for dimension, delta in enumerate((12, 6, 5, 3, 3, 3)):
        for sign in (-1, 1):
            vector = list(REST); vector[dimension] += sign * delta
            cases.append((f"c{dimension}{sign * delta:+d}", vector))
    for name in ("bilabial", "f", "u", "y", "o", "apical", "retroflex", "palatal", "i", "e", "ei", "ao", "ai", "a"):
        cases.append((name, sounds[name]["latentMedian"]))
    report = {}
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=ARGS)
        try:
            def fresh(viewport=None):
                context = browser.new_context(ignore_https_errors=True, viewport=viewport or {"width": 1400, "height": 1000})
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(args.url)
                page.wait_for_function("window.comparisonReady", timeout=60000)
                return context, page

            context, page = fresh()
            assert page.locator(".stages figure").count() == 2
            assert page.locator("#original").count() == 0
            page.evaluate(FORCE, 2)
            rows = []
            for label, vector in cases:
                vector = (list(map(float, vector)) + [0.0] * 12)[:12]
                page.evaluate(SET, vector)
                before = page.evaluate("forcedCalls")
                page.wait_for_timeout(180)
                assert page.evaluate("forcedCalls") > before
                rows.append((label, [image(item) for item in page.evaluate(GRAB, [310, 270, 110, 70])]))
            rows_sheet(rows, args.out / "same-frame-same-vector.png")
            faces = []
            for label, vector in cases:
                if label in {"silence", "bilabial", "u", "palatal", "ai", "a"}:
                    page.evaluate(SET, (list(map(float, vector)) + [0.0] * 12)[:12])
                    page.wait_for_timeout(180)
                    faces.append((label, [image(item) for item in page.evaluate(GRAB, list(FACE))]))
            rows_sheet(faces, args.out / "same-frame-full-face.png", scale=2)
            context.close()

            context, page = fresh()
            report["speech5s"] = speech_run(page, args.out, "speech-5s", "./speech.wav", 0.4, 40)
            context.close()

            context, page = fresh()
            report["speech30s"] = speech_run(page, args.out, "speech-30s", "./speech-30s.wav", 8.0, 40)
            context.close()

            # Interrupting part way must return to the source video, then speak again.
            context, page = fresh()
            report["stopMidSpeech"] = speech_run(page, args.out, "stop-mid-speech", "./speech-30s.wav", 0.4, 0, stop_after=2.2)
            assert report["stopMidSpeech"]["settled"]["stoppedAt"] is not None
            assert report["stopMidSpeech"]["settled"]["stoppedAt"] < 2.5, report["stopMidSpeech"]["settled"]
            page.evaluate("comparison.newer.video.play()")
            report["speakAgainAfterStop"] = speech_run(page, args.out, "speak-again", "./speech.wav", 1.0, 16)
            page.click("#neutral")
            page.wait_for_timeout(150)
            first = page.evaluate("comparison.newer.video.currentTime")
            page.wait_for_timeout(350)
            assert page.evaluate("comparison.newer.video.currentTime") != first
            context.close()

            # A wide column is what pushed the reference's GL canvas out of view.
            context, page = fresh({"width": 1920, "height": 1080})
            report["closeUpChangedPixels"] = close_up_drives_both(page)
            assert min(report["closeUpChangedPixels"]) > 3000, report["closeUpChangedPixels"]
            assert page.evaluate("getComputedStyle(document.querySelector('#native')).transform") == "none"
            context.close()

            # Controls and close-up at the widths people actually open this on.
            context, page = fresh({"width": 1400, "height": 1000})
            page.click("#close-up")
            page.wait_for_timeout(300)
            page.screenshot(path=str(args.out / "page-close-up.png"))
            for width in (320, 375, 414, 768):
                page.set_viewport_size({"width": width, "height": 900})
                page.wait_for_timeout(200)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
                page.screenshot(path=str(args.out / f"page-{width}.png"))
            context.close()
            assert not errors, errors
        finally:
            browser.close()
    (args.out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
