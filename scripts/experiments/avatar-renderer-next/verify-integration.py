"""Real HTTP/Worker/GPU/audio checks for the shared engine and cross-origin SDK."""

import argparse
import base64
import json
import subprocess
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
MONITOR = """(() => {
  window.contexts=[];window.startedSources=[];window.speakingEvents=[];
  const Original=window.AudioContext;
  window.AudioContext=class extends Original {constructor(...args){super(...args);contexts.push(this);}};
  const connect=AudioNode.prototype.connect;
  AudioNode.prototype.connect=function(destination,...rest){
    const result=connect.call(this,destination,...rest);
    if(destination===this.context.destination && !this.context.auditTap){
      this.context.auditTap=this.context.createMediaStreamDestination();connect.call(this,this.context.auditTap);
    }return result;
  };
  const start=AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start=function(when,...rest){startedSources.push({when,samples:this.buffer?.length||0});return start.call(this,when,...rest);};
})();"""
RECORD = """() => {
  const canvas=document.querySelector('canvas');
  const stream=new MediaStream([...canvas.captureStream(30).getVideoTracks(),...contexts[0].auditTap.stream.getAudioTracks()]);
  window.chunks=[];window.recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8,opus'});
  recorder.ondataavailable=e=>chunks.push(e.data);recorder.start(100);
}"""
STOP_RECORD = """async () => {
  await new Promise(resolve=>{recorder.onstop=resolve;recorder.stop();});
  const reader=new FileReader(),done=new Promise(resolve=>reader.onload=()=>resolve(reader.result));
  reader.readAsDataURL(new Blob(chunks,{type:recorder.mimeType}));return (await done).split(';base64,')[1];
}"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="https://127.0.0.1:8787")
    parser.add_argument("--sdk-origin", default="https://10.9.0.32:8787")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--own-rig", action="store_true")
    args = parser.parse_args()
    prefix = "/experiments/avatar-own-rig/" if args.own_rig else "/experiments/avatar-integration/"
    runtime_prefixes = [prefix + "runtime/"] if args.own_rig else ["/avatar-engine/", "/static/sdk/engine/"]
    character = prefix + "sample" if args.own_rig else "/static/characters/dev-123"
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(
        (ROOT / "frontend/app/public/avatar-engine/manifest.json").read_text()
    )
    allowed = set()
    for origin in {args.base, args.sdk_origin}:
        for runtime_prefix in runtime_prefixes:
            allowed.update(origin + runtime_prefix + name for name in manifest["files"])
        for name in [
            "engine.html",
            "sdk.html",
            "openvman-avatar-sdk.js",
            "speech.wav",
            "sample/render_data.json.gz",
            "sample/01.webm",
        ]:
            allowed.add(origin + prefix + name)
        for name in ["render_data.json.gz", "01.webm"]:
            allowed.add(origin + character + "/" + name)
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=[
                "--no-sandbox",
                "--use-gl=angle",
                "--use-angle=gl-egl",
                "--ignore-gpu-blocklist",
            ],
        )
        try:
            for mode in ["engine", "sdk"]:
                context = browser.new_context(
                    ignore_https_errors=True, viewport={"width": 1280, "height": 900}
                )
                errors, unknown, blocked, requests = [], [], [], []

                def route(
                    r, _request, *, requests=requests, blocked=blocked, unknown=unknown
                ):
                    url = r.request.url
                    requests.append(url)
                    if url in allowed:
                        r.continue_()
                    else:
                        blocked.append(url)
                        if "forbidden-control" not in url:
                            unknown.append(url)
                        r.abort()

                context.route("**/*", route)
                context.add_init_script(MONITOR)
                page = context.new_page()
                page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                page.goto(args.base + prefix + f"{mode}.html")
                if mode == "engine":
                    page.wait_for_function("window.engineReady", timeout=30000)
                    page.evaluate('path => engine.loadCharacter(path)', character)
                    # Two distinct character packs use one worker/session/context.
                    page.evaluate(
                        'path => engine.loadCharacter(path)', prefix + "sample"
                    )
                    page.evaluate('path => engine.loadCharacter(path)', character)
                    page.evaluate("""async () => {
                      await engine.player.freeze(2);
                      engine.player.holdControls(new Float32Array(12));engine.player.draw();
                      window.neutral=Array.from(engine.player.context.getImageData(0,0,engine.canvas.width,engine.canvas.height).data);
                      engine.player.holdControls([6,3,0,0,0,0,0,0,0,0,0,0]);engine.player.draw();
                    }""")
                    movement = page.evaluate(
                        """() => {const p=engine.player,d=p.context.getImageData(0,0,engine.canvas.width,engine.canvas.height).data;let n=0;for(let i=0;i<d.length;i+=4)if(Math.max(...[0,1,2].map(c=>Math.abs(d[i+c]-neutral[i+c])))>5)n++;return n;}"""
                    )
                    assert movement > 50, movement
                    page.evaluate("engine.player.holdControls(new Float32Array(12));engine.video.play()")
                else:
                    await_url = (
                        args.sdk_origin
                        + prefix + "openvman-avatar-sdk.js"
                    )
                    page.add_script_tag(url=await_url)
                    page.evaluate(
                        """async ({origin,prefix,ownRig}) => {
                      window.avatar=await OpenVmanAvatar.init({
                        characterId:ownRig?'sample':'dev-123',
                        assetsBaseUrl:origin+(ownRig?prefix:'/static/characters'),
                        ...(ownRig?{runtimeBaseUrl:origin+prefix+'runtime/'}:{})});
                      avatar.on('speaking',event=>speakingEvents.push(event));
                    }""",
                        {"origin": args.sdk_origin, "prefix": prefix, "ownRig": args.own_rig},
                    )
                    movement = None
                page.screenshot(path=str(args.out / f"{mode}-idle.png"))
                page.evaluate("""async () => {
                  for(const path of ['./forbidden-control.wasm','https://forbidden-control.invalid/legacy.js'])try{await fetch(path)}catch{}
                  window.bytes=await(await fetch('./speech.wav')).arrayBuffer();
                  if(!document.querySelector('#play')){const play=document.createElement('button');play.id='play';play.textContent='play';document.body.append(play);}
                  if(!document.querySelector('#stop')){const stop=document.createElement('button');stop.id='stop';stop.textContent='stop';document.body.append(stop);}
                }""")
                page.evaluate(RECORD)
                page.evaluate(
                    """mode => {
                  document.querySelector('#play').onclick=()=>{
                    window.done=false;window.playError=null;
                    const operation=mode==='sdk'?avatar.playAudio(bytes.slice(0)):(async()=>{
                      await engine.prepare();const a=await engine.audioContext.decodeAudioData(bytes.slice(0));
                      await engine.appendPcm(Int16Array.from(a.getChannelData(0),x=>Math.round(x*32767)));await engine.finishAudio();
                    })();
                    operation.then(()=>done=true,error=>{playError=String(error);done=true});
                  };
                  document.querySelector('#stop').onclick=()=>mode==='sdk'?avatar.interrupt():engine.stop();
                }""",
                    mode,
                )
                page.click("#play")
                page.wait_for_timeout(800)
                page.screenshot(path=str(args.out / f"{mode}-speaking.png"))
                page.wait_for_function("window.done", timeout=20000)
                assert not page.evaluate("window.playError"), page.evaluate(
                    "window.playError"
                )
                encoded = page.evaluate(STOP_RECORD)
                recording = args.out / f"{mode}-speech.webm"
                recording.write_bytes(base64.b64decode(encoded, validate=True))
                samples = np.frombuffer(
                    subprocess.check_output(
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
                    ),
                    dtype="<f4",
                )
                facts = page.evaluate(
                    "({contextCount:contexts.length,scheduledSamples:startedSources.reduce((n,s)=>n+s.samples,0),speaking:speakingEvents})"
                )
                facts.update(
                    decodedSeconds=len(samples) / 16000,
                    rms=float(np.sqrt(np.mean(samples**2))),
                    changedPixels=movement,
                )
                assert (
                    facts["contextCount"] == 1 and facts["scheduledSamples"] == 80000
                ), facts
                assert facts["decodedSeconds"] >= 4.8 and facts["rms"] > 0.01, facts
                # Actual active audio interruption, followed by a second playback.
                page.click("#play")
                page.wait_for_timeout(500)
                page.click("#stop")
                page.wait_for_timeout(100)
                if mode == "engine":
                    diagnostics = page.evaluate("engine.diagnostics()")
                    assert diagnostics["sources"] == 0 and all(
                        x == 0 for x in diagnostics["controls"]
                    ), diagnostics
                    page.evaluate("engine.dispose()")
                else:
                    assert page.evaluate("speakingEvents.at(-1).state") == "stop"
                    page.evaluate("avatar.destroy()")
                assert len(blocked) == 2 and not errors and not unknown, {
                    "errors": errors,
                    "unknown": unknown,
                    "blocked": blocked,
                }
                facts.update(
                    unexpectedRequests=unknown,
                    errors=errors,
                    requests=sorted(set(requests)),
                    blocked=blocked,
                )
                results[mode] = facts
                context.close()
        finally:
            browser.close()
    (args.out / "summary.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
