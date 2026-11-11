"""Exercise the deployed renderer; a supplied reference is used only in the audit browser."""

import argparse
import base64
import importlib.util
import json
import subprocess
from pathlib import Path
from urllib.parse import urljoin

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", default="https://127.0.0.1:8787/experiments/avatar-renderer-next/"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--reference-samples", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_spec = importlib.util.spec_from_file_location(
        "candidate_install", ROOT / "install.py"
    )
    install = importlib.util.module_from_spec(manifest_spec)
    manifest_spec.loader.exec_module(install)
    _, manifest = install.package()
    allowed = {urljoin(args.url, name) for name in manifest} | {args.url}
    errors, unexpected, blocked, requested = [], [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=[
                "--no-sandbox",
                "--use-gl=angle",
                "--use-angle=gl-egl",
                "--ignore-gpu-blocklist",
                "--enable-gpu-rasterization",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        context = browser.new_context(
            ignore_https_errors=True, viewport={"width": 1280, "height": 900}
        )

        def route(request_route):
            url = request_route.request.url
            requested.append(url)
            if url in allowed:
                request_route.continue_()
            else:
                blocked.append(url)
                if "/forbidden-control." not in url:
                    unexpected.append(url)
                request_route.abort()

        context.route("**/*", route)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url)
        page.wait_for_function("!!window.demo", timeout=30000)
        gpu = page.evaluate(
            """() => {const g=demo.player.renderer.gl;return g.getParameter(g.getExtension('WEBGL_debug_renderer_info').UNMASKED_RENDERER_WEBGL);}"""
        )
        page.evaluate(
            """async () => {for(const path of ['forbidden-control.wasm','forbidden-control.js']) {try {await fetch(path);} catch {}}}"""
        )
        assert len(blocked) == 2, blocked
        page.evaluate("demo.freeze()")
        page.screenshot(path=str(args.out / "neutral.png"))
        neutral = page.evaluate(
            "Array.from(demo.player.context.getImageData(330,285,80,60).data)"
        )
        page.evaluate("demo.freeze([.35,.28])")
        opened = page.evaluate(
            "Array.from(demo.player.context.getImageData(330,285,80,60).data)"
        )
        changed = int(
            np.any(
                np.array(neutral).reshape(-1, 4)[:, :3]
                != np.array(opened).reshape(-1, 4)[:, :3],
                axis=1,
            ).sum()
        )
        assert changed > 50, f"Mouth intervention has no visible effect: {changed}"
        page.screenshot(path=str(args.out / "open.png"))
        page.click("#speak")
        page.wait_for_function(
            'demo.controller.state === "playing" && demo.controller.bsTimeline.length > 10'
        )
        page.wait_for_timeout(800)
        page.wait_for_function(
            "demo.controller.liveSources.size > 0 && demo.player.controls.some(x=>Math.abs(x)>.001)"
        )
        page.screenshot(path=str(args.out / "speaking.png"))
        speaking = page.evaluate(
            "({steps:demo.controller.bsTimeline.length,sources:demo.controller.liveSources.size,controls:Array.from(demo.player.controls)})"
        )
        assert speaking["sources"] > 0 and any(
            abs(x) > 0.001 for x in speaking["controls"]
        ), speaking
        page.click("#stop")
        page.wait_for_timeout(100)
        stopped = page.evaluate(
            "({sources:demo.controller.liveSources.size,controls:Array.from(demo.player.controls),paint:demo.player.paints.at(-1)})"
        )
        assert stopped["sources"] == 0 and all(x == 0 for x in stopped["controls"]), (
            stopped
        )
        assert all(x == 0 for x in stopped["paint"]["controls"]), stopped
        # Full playback exercises EOS as well as the earlier active interruption.
        page.evaluate("""() => {
          window.liveAudit={active:0,neutralWhileSounding:0,states:[]};
          const c=demo.controller,original=c.onFrame;
          c.onFrame=frame=>{
            const now=demo.audioContext.currentTime;
            if(c.scheduledAudioList.some(s=>s.startTime<=now && now<s.endTime)){
              liveAudit.active++;
              if(frame.bsVec.every(x=>x===0))liveAudit.neutralWhileSounding++;
            }
            original(frame);
          };
          const onState=c.onStateChange;
          c.onStateChange=(state,previous,details)=>{liveAudit.states.push({state,details});onState(state,previous,details);};
          const tracks=[...document.querySelector('#stage').captureStream(30).getVideoTracks(),...demo.recordDestination.stream.getAudioTracks()];
          window.auditRecorder=new MediaRecorder(new MediaStream(tracks),{mimeType:'video/webm;codecs=vp8,opus'});
          window.auditChunks=[];auditRecorder.ondataavailable=e=>auditChunks.push(e.data);auditRecorder.start(100);
        }""")
        page.click("#speak")
        page.wait_for_function('demo.controller.state === "playing"')
        page.wait_for_function(
            'demo.controller.state === "ready" && demo.controller.totalPcmSamples > 0',
            timeout=15000,
        )
        replay = page.evaluate(
            "({steps:demo.controller.bsTimeline.length,samples:demo.controller.totalPcmSamples,controls:Array.from(demo.player.controls)})"
        )
        assert replay["steps"] == 125 and replay["samples"] == 80000, replay
        assert all(x == 0 for x in replay["controls"]), replay
        live = page.evaluate("liveAudit")
        assert live["active"] > 50 and live["neutralWhileSounding"] == 0, live
        encoded = page.evaluate("""async () => {
          await new Promise(resolve=>{auditRecorder.onstop=resolve;auditRecorder.stop();});
          const reader=new FileReader();const loaded=new Promise(resolve=>reader.onload=()=>resolve(reader.result));
          reader.readAsDataURL(new Blob(auditChunks,{type:auditRecorder.mimeType}));
          return (await loaded).split(';base64,')[1];
        }""")
        recording = args.out / "speech.webm"
        recording.write_bytes(base64.b64decode(encoded, validate=True))
        decoded = subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(recording),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "f32le",
                "-",
            ]
        )
        audio = np.frombuffer(decoded, dtype="<f4")
        recording_info = {
            "bytes": recording.stat().st_size,
            "decodedAudioSeconds": len(audio) / 16000,
            "rms": float(np.sqrt(np.mean(audio**2))),
        }
        assert (
            recording_info["decodedAudioSeconds"] >= 4.8
            and recording_info["rms"] > 0.01
        ), recording_info
        frame_costs = page.evaluate("demo.player.paints.map(p=>p.durationMs)")
        costs = {f"p{p}": float(np.percentile(frame_costs, p)) for p in [50, 95, 99]}
        assert costs["p95"] < 40, costs
        assert not errors and not unexpected, {
            "errors": errors,
            "unexpected": unexpected,
        }
        assert not any(
            "OpenVmanAvatarRuntime" in url or "model_lip" in url for url in requested
        )
        responsive = []
        for width in [320, 375, 414, 768]:
            page.set_viewport_size({"width": width, "height": 900})
            responsive.append(
                page.evaluate(
                    "({width:innerWidth,scroll:document.documentElement.scrollWidth})"
                )
            )
        assert all(row["scroll"] == row["width"] for row in responsive), responsive
        result = {
            "url": args.url,
            "gpu": gpu,
            "unexpectedRequests": unexpected,
            "errors": errors,
            "positiveBlockControls": blocked,
            "requested": sorted(set(requested)),
            "changedMouthPixels": changed,
            "speaking": speaking,
            "stopped": stopped,
            "fullPlayback": replay,
            "liveAudioAudit": live,
            "recording": recording_info,
            "responsive": responsive,
            "frameCostMs": costs,
        }
        context.close()

        if args.reference:
            assert args.reference_samples, (
                "--reference-samples required for reference audit"
            )
            # This second context explicitly injects a historical reference. It is never deployed.
            audit = browser.new_context(ignore_https_errors=True)
            page = audit.new_page()
            page.goto(args.url)
            page.wait_for_function("!!window.demo", timeout=30000)
            page.evaluate(
                """async ({source,samples}) => {
              await demo.freeze();
              const module = await import(URL.createObjectURL(new Blob([source],{type:'text/javascript'})));
              const canvas=document.createElement('canvas');canvas.width=canvas.height=180;
              const reference=new module.AvatarRenderer(canvas);
              const a=demo.player.character;
              await reference.init({vboData:a.vertices,iboData:a.indices,texBsData:a.morph,
                texTeethData:a.teeth,texVertBufferData:new Uint8Array(465*16),samples32:samples,jsonData:a.frames});
              window.auditReference={reference,canvas};
            }""",
                {
                    "source": args.reference.read_text(),
                    "samples": json.loads(args.reference_samples.read_text()),
                },
            )
            cases = {}
            strips = []
            for name, values in {
                "neutral": [0] * 12,
                "open": [0.35, 0.28] + [0] * 10,
                "negative": [-0.2, -0.1, 0.15, 0, 0, 0] + [0] * 6,
                "third": [0, 0, 0.5] + [0] * 9,
                "speech": speaking["controls"],
            }.items():
                data = page.evaluate(
                    """async values => {
                  await demo.freeze(values);
                  const p=demo.player,r=auditReference;
                  r.reference.render(p.videoFrame,p.controls,p.skin);
                  const pixels=c=>{const t=document.createElement('canvas');t.width=t.height=180;const x=t.getContext('2d');x.drawImage(c,0,0);return Array.from(x.getImageData(0,0,180,180).data);};
                  return {candidate:pixels(p.surface),reference:pixels(r.canvas),frame:p.videoFrame};
                }""",
                    values,
                )
                arrays = [
                    np.array(data[key], dtype=np.uint8).reshape(180, 180, 4)
                    for key in ["reference", "candidate"]
                ]
                diff = np.abs(
                    arrays[0][:, :, :3].astype(float)
                    - arrays[1][:, :, :3].astype(float)
                )
                cases[name] = {
                    "frame": data["frame"],
                    "mae": float(diff.mean()),
                    "max": float(diff.max()),
                    "over30": int(np.any(diff > 30, axis=2).sum()),
                    "mouthMae": float(diff[60:125, 45:145].mean()),
                }
                # This gates shape/placement, not exact historical tooth lighting.
                assert cases[name]["mae"] < 3 and cases[name]["mouthMae"] < 12, cases[
                    name
                ]
                strips.append(np.concatenate(arrays, axis=1))
            Image.fromarray(np.concatenate(strips, axis=0)).save(
                args.out / "reference-comparison.png"
            )
            result["referenceComparison"] = cases
            audit.close()
        browser.close()
    (args.out / "summary.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
