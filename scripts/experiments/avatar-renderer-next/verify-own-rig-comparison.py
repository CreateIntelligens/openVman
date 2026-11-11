"""Real ncnn/ONNX same-audio comparison with a fixed-video causal check."""

import argparse
import base64
import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='https://127.0.0.1:8787/experiments/avatar-own-rig/compare.html')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('verification', Path(__file__).with_name('verify-integration.py'))
    verification = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verification)
    errors, rows = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True,
            args=['--no-sandbox', '--use-gl=angle', '--use-angle=gl-egl', '--ignore-gpu-blocklist'])
        try:
            context = browser.new_context(ignore_https_errors=True, viewport={'width':1400,'height':1000})
            context.add_init_script(verification.MONITOR)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(args.url)
            page.wait_for_function('window.comparisonReady', timeout=60000)
            assert page.locator('#original').count()==0
            assert page.locator('.stages figure').count()==2
            # Observe the true original GPU coefficients without writing its heap.
            page.evaluate('''()=>{
              window.nativeUniforms=[];const g=comparison.native.instance.ctx,original=g.uniform1fv.bind(g);
              g.uniform1fv=(location,values,start,count)=>{
                if(count===12)nativeUniforms.push(Array.from(values.subarray(start,start+12)));
                else if(values.length===12)nativeUniforms.push(Array.from(values));
                return original(location,values,...(start===undefined?[]:[start,count]));
              };
              const c=document.createElement('canvas');c.width=720;c.height=640;window.recordCanvas=c;
              const draw=()=>{const x=c.getContext('2d');
                x.drawImage(comparison.native.canvas,0,0,360,640);
                x.drawImage(comparison.newer.canvas,360,0,360,640);
                window.recordRaf=requestAnimationFrame(draw);
              };draw();
              const stream=new MediaStream([...c.captureStream(30).getVideoTracks(),...comparison.newer.audioContext.auditTap.stream.getAudioTracks()]);
              window.chunks=[];window.recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8,opus'});
              recorder.ondataavailable=e=>chunks.push(e.data);recorder.start(100);
            }''')
            page.click('#play')
            page.wait_for_function('comparison.native.telemetry.chunks===20')
            # Hold the source frame: mouth changes now cannot come from body/video motion.
            page.evaluate('''async()=>{const v=comparison.newer.video;v.pause();
              if(Math.abs(v.currentTime-2)>.001)await new Promise(r=>{v.addEventListener('seeked',r,{once:true});v.currentTime=2});
            }''')
            for index in range(18):
                page.wait_for_timeout(150)
                row=page.evaluate('''()=>{
                  const {native,newer}=comparison;
                  const raw=document.createElement('canvas');raw.width=newer.canvas.width;raw.height=newer.canvas.height;raw.getContext('2d').drawImage(newer.video,0,0);
                  const images=[raw,native.canvas,newer.canvas].map(source=>{
                    const c=document.createElement('canvas');c.width=150;c.height=100;
                    c.getContext('2d').drawImage(source,285,255,150,100,0,0,150,100);return c.toDataURL();
                  });
                  return {images,time:newer.video.currentTime,uniform:nativeUniforms.at(-1),controls:Array.from(newer.player.controls)};
                }''')
                assert abs(row['time']-2)<.001
                for label, data in zip(('source','native','v2'),row.pop('images')):
                    (args.out/f'{label}-{index:02}.png').write_bytes(base64.b64decode(data.split(';base64,')[1]))
                rows.append(row)
            page.screenshot(path=str(args.out/'speaking.png'))
            page.wait_for_function('document.querySelector("#status").textContent==="播放完成"', timeout=15000)
            encoded=page.evaluate(verification.STOP_RECORD)
            (args.out/'same-audio.webm').write_bytes(base64.b64decode(encoded,validate=True))
            page.evaluate('cancelAnimationFrame(recordRaf)')
            page.wait_for_timeout(150)
            facts=page.evaluate('''()=>({native:comparison.native.telemetry,
              contexts:contexts.length,scheduledSamples:startedSources.reduce((n,s)=>n+s.samples,0),
              sharedVideo:document.querySelector('#native').contentWindow.characterVideo===comparison.newer.video,
              controls:Array.from(comparison.newer.player.controls)})''')
            assert facts['native']['samples']==80000 and facts['native']['chunks']==20
            assert facts['sharedVideo'] and facts['scheduledSamples']==80000 and facts['contexts']==1, facts
            assert all(value==0 for value in facts['controls'])
            for label in ('native','v2'):
                arrays=[np.asarray(Image.open(args.out/f'{label}-{index:02}.png')).astype(int) for index in range(18)]
                changed=max(int((np.abs(a-arrays[0]).max(axis=2)>5).sum()) for a in arrays[1:])
                assert changed>50, (label,changed)
                facts[label+'FixedFrameChangedPixels']=changed
            uniforms=np.asarray([r['uniform'] for r in rows if r['uniform']])
            assert len(uniforms)>5 and np.ptp(uniforms[:,0])>1, uniforms
            facts['nativeJawRange']=[float(uniforms[:,0].min()),float(uniforms[:,0].max())]
            for width in (320,375,414,768):
                page.set_viewport_size({'width':width,'height':900})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            page.click('#neutral')
            a=page.evaluate('comparison.newer.video.currentTime');page.wait_for_timeout(350)
            b=page.evaluate('comparison.newer.video.currentTime');assert b!=a
            assert not errors,errors
            context.close()
        finally:
            browser.close()
    contact=Image.new('RGB',(300,600),'white')
    for row,index in enumerate((0,2,5,8,11,15)):
        for column,label in enumerate(('native','v2')):
            contact.paste(Image.open(args.out/f'{label}-{index:02}.png'),(column*150,row*100))
    contact.save(args.out/'native-v2.png')
    (args.out/'summary.json').write_text(json.dumps({'facts':facts,'samples':rows,'errors':errors},indent=2))
    print(json.dumps(facts))


if __name__=='__main__':
    main()
