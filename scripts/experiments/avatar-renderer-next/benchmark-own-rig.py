"""Sequential same-video/audio comparison of renderer revisions.

CPU command submission and asynchronous GPU timer queries are separate metrics.
No screenshot capture or recording runs during the timed performance window.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright


SETUP = """async seconds => {
  await engine.prepare();
  const data=await (await fetch('./speech.wav')).arrayBuffer();
  const audio=await engine.audioContext.decodeAudioData(data);
  const input=audio.getChannelData(0);
  window.pcm=Int16Array.from({length:16000*seconds},(_,i)=>Math.round(input[i%input.length]*32767));
  const p=engine.player,g=p.renderer.gl;
  const ext=g.getExtension('EXT_disjoint_timer_query_webgl2');
  window.measurement={draw:[],gpu:[],frames:[],starts:[],disjoint:0,gpuTimerAvailable:!!ext};
  const queries=[];
  const render=p.renderer.render.bind(p.renderer);
  p.renderer.render=(...args)=>{
    let query;
    if(ext){query=g.createQuery();g.beginQuery(ext.TIME_ELAPSED_EXT,query);}
    try{return render(...args)}finally{if(query){g.endQuery(ext.TIME_ELAPSED_EXT);queries.push(query)}}
  };
  const draw=p.draw.bind(p);
  p.draw=()=>{
    const start=performance.now();draw();
    measurement.draw.push(performance.now()-start);
    measurement.frames.push({at:performance.now(),frame:p.videoFrame});
    while(queries.length && g.getQueryParameter(queries[0],g.QUERY_RESULT_AVAILABLE)){
      const query=queries.shift();
      if(!g.getParameter(ext.GPU_DISJOINT_EXT))measurement.gpu.push(g.getQueryParameter(query,g.QUERY_RESULT)/1e6);
      else measurement.disjoint++;
      g.deleteQuery(query);
    }
  };
  const source=engine.audioContext.createBufferSource.bind(engine.audioContext);
  engine.audioContext.createBufferSource=()=>{
    const s=source(),start=s.start.bind(s);
    s.start=(when,...rest)=>{measurement.starts.push({at:performance.now(),when,now:engine.audioContext.currentTime,samples:s.buffer.length});return start(when,...rest)};
    return s;
  };
  await engine.video.play();
  measurement.draw=[];measurement.frames=[];measurement.gpu=[];
}"""


def quantiles(values):
    if not values:
        return None
    return {key: float(np.percentile(values, percentile)) for key, percentile in
            (("p50", 50), ("p95", 95), ("p99", 99), ("max", 100))}


def memory(processes):
    totals = {"rssMB": 0.0, "pssMB": 0.0}
    for pid in processes:
        try:
            for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
                for field, key in (("Rss:", "rssMB"), ("Pss:", "pssMB")):
                    if line.startswith(field):
                        totals[key] += float(line.split()[1]) / 1024
        except (OSError, ValueError):
            pass
    return totals


def serve_file(path):
    """Serve a local character file with range support, so the video can loop."""
    data = path.read_bytes()
    kind = "video/webm" if path.suffix == ".webm" else "application/gzip"

    def handler(route):
        wanted = route.request.headers.get("range")
        if not wanted:
            route.fulfill(body=data, content_type=kind, headers={"Accept-Ranges": "bytes"})
            return
        first, _, last = wanted.removeprefix("bytes=").partition("-")
        start = int(first or 0)
        end = int(last) if last else len(data) - 1
        route.fulfill(status=206, body=data[start:end + 1], content_type=kind, headers={
            "Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{len(data)}",
        })
    return handler


def fulfill_with(body):
    def handler(route):
        route.fulfill(body=body, content_type="application/javascript")
    return handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="https://127.0.0.1:8787")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--groups", type=int, default=3)
    parser.add_argument("--baseline-runtime", type=Path,
                        help="Saved engine folder to compare with the live one on the same v2 page; "
                             "the adapter, renderer and player change together, so one file alone will not load")
    parser.add_argument("--character-dir", type=Path,
                        help="Local folder with 01.webm and render_data.json.gz to measure instead of the "
                             "published sample; composite size follows the character, so size affects cost")
    args = parser.parse_args()
    baseline = None
    if args.baseline_runtime:
        baseline = {
            name: (args.baseline_runtime / name).read_bytes()
            for name in ("character-adapter.mjs", "renderer.mjs", "frame-player.mjs",
                         "frame-sync.mjs", "index.mjs", "inference/streaming-playback.mjs")
        }
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome", headless=True,
            args=["--no-sandbox", "--use-gl=angle", "--use-angle=gl-egl",
                  "--ignore-gpu-blocklist"],
        )
        cdp = browser.new_browser_cdp_session()
        hardware = cdp.send("SystemInfo.getInfo")
        browser.close()
        try:
            for group in range(args.groups):
                versions = ["before", "after"] if baseline is not None else ["v1", "v2"]
                for version in (versions if group % 2 == 0 else versions[::-1]):
                    browser = p.chromium.launch(
                        executable_path="/usr/bin/google-chrome", headless=True,
                        args=["--no-sandbox", "--use-gl=angle", "--use-angle=gl-egl",
                              "--ignore-gpu-blocklist"],
                    )
                    cdp = browser.new_browser_cdp_session()
                    context = browser.new_context(ignore_https_errors=True)
                    if version == "before":
                        for name, body in baseline.items():
                            context.route(f"**/runtime/core/{name}", fulfill_with(body))
                    if args.character_dir:
                        for name in ("01.webm", "render_data.json.gz"):
                            context.route(f"**/sample/{name}", serve_file(args.character_dir / name))
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    prefix = "/experiments/avatar-integration/" if version == "v1" else "/experiments/avatar-own-rig/"
                    begin = time.monotonic()
                    page.goto(args.base + prefix + "engine.html")
                    try:
                        page.wait_for_function("window.engineReady", timeout=60000)
                    except Exception:
                        status = page.locator("#status").text_content(timeout=1000)
                        raise RuntimeError(f"{version} group {group + 1} never became ready: {status}; page errors {errors}")
                    ready_ms = (time.monotonic() - begin) * 1000
                    page.evaluate("engine.loadCharacter('./sample')")
                    page.evaluate(SETUP, args.seconds)
                    adapter_sha = None
                    if baseline is not None:
                        adapter_sha = page.evaluate("""async () => {
                          const bytes=await(await fetch('./runtime/core/character-adapter.mjs')).arrayBuffer();
                          const digest=await crypto.subtle.digest('SHA-256',bytes);
                          return Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
                        }""")
                    before = {row["id"]: row["cpuTime"] for row in cdp.send("SystemInfo.getProcessInfo")["processInfo"]}
                    mem_before = memory(before)
                    wall_start = time.monotonic()
                    page.evaluate("""() => {
                      window.finished=false;window.playError=null;measurement.requestAt=performance.now();
                      (async()=>{await engine.appendPcm(pcm);await engine.finishAudio()})()
                        .then(()=>finished=true,error=>{playError=String(error);finished=true});
                    }""")
                    page.wait_for_function("window.finished", timeout=(args.seconds + 30) * 1000)
                    elapsed = time.monotonic() - wall_start
                    after = cdp.send("SystemInfo.getProcessInfo")["processInfo"]
                    cpu_seconds = sum(max(0, row["cpuTime"] - before.get(row["id"], row["cpuTime"])) for row in after)
                    data = page.evaluate("({measurement,controls:Array.from(engine.player.controls),error:playError})")
                    assert not errors and not data["error"], (errors, data["error"])
                    assert all(value == 0 for value in data["controls"]), data["controls"]
                    m = data["measurement"]
                    assert sum(s["samples"] for s in m["starts"]) == args.seconds * 16000
                    start = m["starts"][0]
                    first_audio_ms = start["at"] - m["requestAt"] + (start["when"] - start["now"]) * 1000
                    distinct = [f for i, f in enumerate(m["frames"]) if i == 0 or f["frame"] != m["frames"][i-1]["frame"]]
                    intervals = np.diff([f["at"] for f in distinct]).tolist()
                    row = {
                        "group": group + 1, "version": version, "seconds": args.seconds,
                        "adapterSha256": adapter_sha,
                        "readyMs": ready_ms, "firstScheduledAudioMs": first_audio_ms,
                        "cpuPercentOneCore": cpu_seconds / elapsed * 100,
                        "memoryBefore": mem_before, "memoryAfter": memory([r["id"] for r in after]),
                        "distinctVideoFps": (len(distinct)-1) / ((distinct[-1]["at"]-distinct[0]["at"])/1000),
                        "drawSubmissionMs": quantiles(m["draw"]),
                        "gpuMs": quantiles(m["gpu"]), "gpuTimerAvailable": m["gpuTimerAvailable"],
                        "gpuDisjointSamples": m["disjoint"], "videoIntervalMs": quantiles(intervals),
                        "endControls": data["controls"], "errors": errors,
                    }
                    intervals_ms = row["videoIntervalMs"]
                    # Distinct decoded frames: repainting at the display rate does not count.
                    row["meetsPlayback"] = (
                        row["distinctVideoFps"] >= 23.75
                        and intervals_ms["p95"] <= 80 and intervals_ms["max"] < 500
                    )
                    results.append(row)
                    (args.out / f"{version}-{group+1}-raw.json").write_text(json.dumps(m))
                    (args.out / "summary.json").write_text(json.dumps({"hardware": hardware["gpu"], "runs": results}, indent=2))
                    print(json.dumps(row), flush=True)
                    page.evaluate("engine.dispose()")
                    context.close()
                    browser.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
