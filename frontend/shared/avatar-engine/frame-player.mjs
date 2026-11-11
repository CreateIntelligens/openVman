import { repairFrameSyncCorner } from "./frame-sync.mjs";
import { CharacterBinding, MouthDynamics, decodeMouthPose } from "./character-adapter.mjs";
import { SurfaceRenderer } from "./renderer.mjs";

/** Video decoding and compositing use DOM coordinates, independently of GPU coordinates. */
export class FramePlayer {
  constructor(canvas, video, character) {
    this.canvas = canvas;
    this.video = video;
    this.character = character;
    this.context = canvas.getContext("2d", { willReadFrequently: true });
    // The mesh lives in 180 units, but its pixels must outnumber the video's or the
    // whole crop visibly softens the moment a large character starts speaking.
    const side = Math.max(...character.frames.map(({ region }) => region[2] - region[0]));
    this.surfaceSize = Math.max(180, Math.min(360, Math.ceil(side * 1.25)));
    this.skin = document.createElement("canvas");
    this.skin.width = this.skin.height = this.surfaceSize;
    this.skinContext = this.skin.getContext("2d");
    this.surface = document.createElement("canvas");
    this.surface.width = this.surface.height = this.surfaceSize;
    this.binding = new CharacterBinding(character);
    this.renderer = new SurfaceRenderer(this.surface, character);
    this.controls = new Float32Array(12);
    this.dynamics = new MouthDynamics();
    this.videoFrame = 0;
    this.paints = [];
    this.running = false;
  }

  draw() {
    if (this.videoSource) this.video = this.videoSource();
    if (this.video.readyState < 2) return;
    const started = performance.now();
    const { context: ctx, canvas, video } = this;
    ctx.save();
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "copy";
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    // The supplied video carries a modulo-seven frame marker. Decode before repairing it.
    const marker = ctx.getImageData(canvas.width - 2, 0, 2, 2).data;
    let sum = 0;
    for (let i = 0; i < marker.length; i += 4)
      sum += marker[i] + marker[i + 1] + marker[i + 2];
    const phase = Math.round(sum / 12 / 40);
    const estimate = Math.floor(video.currentTime * 25);
    const matches = Array.from(
      { length: 7 },
      (_, i) => estimate + i - 3,
    ).filter((n) => n >= 0 && n % 7 === phase);
    this.videoFrame = matches[0] ?? estimate;
    repairFrameSyncCorner(ctx, canvas);
    const [x, y, right, bottom] = this.binding.region(this.videoFrame);
    const size = this.surfaceSize;
    this.skinContext.clearRect(0, 0, size, size);
    this.skinContext.drawImage(canvas, x, y, right - x, bottom - y, 0, 0, size, size);
    // Paint rate varies, so the pose eases by elapsed time rather than per paint.
    const elapsed = Math.min(0.1, (started - (this.lastDraw ?? started)) / 1000);
    this.lastDraw = started;
    const pose = this.dynamics.step(decodeMouthPose(this.controls), elapsed);
    const geometry = this.binding.update(this.videoFrame, this.controls, pose);
    this.lastGeometry = geometry;
    // A neutral control vector keeps the source frame byte-for-byte: sending
    // the crop through two resamplers would soften a resting mouth.
    if (!geometry.neutral && geometry.activity > 0) {
      this.renderer.render(geometry, this.skin);
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = geometry.activity;
      ctx.drawImage(this.surface, x, y, right - x, bottom - y);
    }
    ctx.restore();
    this.paints.push({
      at: performance.now(),
      durationMs: performance.now() - started,
      frame: this.videoFrame,
      controls: Array.from(this.controls),
    });
    if (this.paints.length > 300) this.paints.shift();
  }

  /** Coefficients arrive every 40 ms; blending between them removes the staircase. */
  setControls(current, next, phase = 0) {
    for (let i = 0; i < this.controls.length; i++) {
      this.controls[i] = next ? current[i] + (next[i] - current[i]) * phase : current[i];
    }
  }

  /** Stop speaking: the mouth eases shut while painting, or at once when it is not. */
  releaseControls() {
    this.controls.fill(0);
    if (!this.running) this.dynamics.snap();
  }

  /** Pose a frozen frame directly; live playback eases through draw() instead. */
  holdControls(vector) {
    this.controls.set(vector);
    this.dynamics.snap(decodeMouthPose(this.controls));
  }

  start() {
    if (this.running) return;
    this.running = true;
    const draw = () => {
      if (!this.running) return;
      this.draw();
      this.raf = requestAnimationFrame(draw);
    };
    this.raf = requestAnimationFrame(draw);
  }

  async freeze(seconds = 2) {
    this.video.pause();
    if (this.video.currentTime !== seconds) {
      const sought = new Promise((resolve) =>
        this.video.addEventListener("seeked", resolve, { once: true }),
      );
      this.video.currentTime = seconds;
      await sought;
    }
    this.draw();
  }

  pause() { this.running = false; cancelAnimationFrame(this.raf); }

  dispose({ keepVideo = false } = {}) {
    this.pause();
    if (!keepVideo) this.video.pause();
    this.renderer.dispose();
  }
}
