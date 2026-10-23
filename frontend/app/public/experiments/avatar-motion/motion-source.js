const base = "/static/characters/0624/motion-lab";

export const motionSource = Object.freeze({
  id: "hciot-v1", assetsBaseUrl: base,
  dataUrl: `${base}/hciot-v1/combined_data.json.gz`,
  videoUrl: `${base}/hciot-v1/01.webm`,
  manifestUrl: `${base}/hciot-v1/manifest.json`,
});

export const labels = Object.freeze({
  idle: "待機", thinking: "思考", speaking: "說話", greeting: "比心", bye: "道別",
});

// One correctly indexed bundle, with independently prepared per-clip geometry.
// The neutral waiting clip also provides the unobstructed speaking base.
export const segments = Object.freeze({
  idle: { start: 0, end: 8, clip: "waiting-command.mp4" },
  thinking: { start: 8, end: 16, clip: "thinking.mp4" },
  speaking: { start: 0, end: 8, clip: "waiting-command.mp4" },
  greeting: { start: 16, end: 24, clip: "idle.mp4", loop: false, next: "idle" },
  bye: { start: 24, end: 32, clip: "bye.mp4", loop: false, next: "idle" },
});

export function validateMotionManifest(manifest) {
  if (manifest?.id !== motionSource.id || manifest.fps !== 25
      || manifest.frameCount !== 800 || manifest.width !== 1080 || manifest.height !== 1920) {
    throw new Error("動作素材版本或影片規格不符，請重新準備 HCIOT 素材包。");
  }
  for (const state of ["idle", "thinking", "greeting", "bye"]) {
    const actual = manifest.segments?.[state], expected = segments[state];
    if (actual?.start !== expected.start || actual?.end !== expected.end) {
      throw new Error(`動作素材的 ${labels[state]} 時間軸不符，尚未啟動對嘴引擎。`);
    }
  }
}
