/** Explicit original-runtime reference, isolated from the ncnn-free candidate. */
import { installIdleLipSyncBypass } from '../../../frontend/avatar-sdk/src/idleLipSyncBypass';
import { installFrameSyncMarkerRepair } from '../../../frontend/shared/avatar/avatarFrameSyncRepair';

const state = window as any;
state.nativeReady = (async () => {
  const idle = installIdleLipSyncBypass();
  const marker = installFrameSyncMarkerRepair();
  const instance = await state.createQtAppInstance({
    locateFile: (name: string) => name.endsWith('.wasm')
      ? new URL('./OpenVmanAvatarRuntime.wasm', location.href).href : name,
  });
  const response = await fetch('./combined_data.json.gz');
  if (!response.ok) throw new Error(`Original character package: ${response.status}`);
  const stream = response.body!.pipeThrough(new DecompressionStream('gzip'));
  const text = await new Response(stream).text();
  const bytes = new TextEncoder().encode(text);
  const pointer = instance._malloc(bytes.length + 1);
  try {
    instance.stringToUTF8(text, pointer, bytes.length + 1);
    instance._processSecret(pointer);
  } finally { instance._free(pointer); }
  let index = 0;
  const telemetry = { chunks: 0, samples: 0, sharedVideo: false };
  const reference = {
    telemetry,
    attachVideo(video: HTMLVideoElement) {
      state.characterVideo.pause();
      state.characterVideo = video;
      telemetry.sharedVideo = true;
    },
    beginPcm(pcm: Int16Array) {
      reference.stop();
      idle?.beginSpeaking();
      for (let offset = 0; offset < pcm.length; offset += 4096) {
        const chunk = pcm.subarray(offset, offset + 4096);
        const address = instance._malloc(chunk.byteLength);
        try {
          instance.HEAPU8.set(new Uint8Array(chunk.buffer, chunk.byteOffset, chunk.byteLength), address);
          instance._setAudioBuffer(address, chunk.byteLength, index++);
          telemetry.chunks++;telemetry.samples += chunk.length;
        } finally { instance._free(address); }
      }
    },
    stop() {
      instance._clearAudio();index = 0;idle?.resetSpeaking();
    },
    canvas: document.querySelector('#canvas_video'),
    instance,
  };
  state.nativeReference = reference;
  window.addEventListener('pagehide', () => { reference.stop();idle?.restore();marker?.restore(); }, {once:true});
  return reference;
})().catch((error: Error) => { state.nativeError=String(error);throw error; });
