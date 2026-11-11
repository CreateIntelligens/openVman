import { CharacterBinding } from "./character-adapter.mjs";
import { SurfaceRenderer } from "./renderer.mjs";

/** Video decoding and compositing use DOM coordinates, independently of GPU coordinates. */
export class FramePlayer {
  constructor(canvas, video, character) {
    this.canvas = canvas;
    this.video = video;
    this.character = character;
    this.context = canvas.getContext("2d", { willReadFrequently: true });
    this.skin = document.createElement("canvas");
    this.skin.width = this.skin.height = 180;
    this.skinContext = this.skin.getContext("2d");
    this.surface = document.createElement("canvas");
    this.surface.width = this.surface.height = 180;
    this.binding = new CharacterBinding(character);
    this.renderer = new SurfaceRenderer(this.surface, character);
    this.controls = new Float32Array(12);
    this.videoFrame = 0;
    this.paints = [];
    this.running = false;
  }

  draw() {
    if (this.video.readyState < 2) return;
    const started = performance.now();
    const { context: ctx, canvas, video } = this;
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
    const patch = ctx.getImageData(canvas.width - 3, 0, 1, 1);
    for (let x = canvas.width - 2; x < canvas.width; x++) {
      ctx.putImageData(patch, x, 0);
      ctx.putImageData(patch, x, 1);
    }
    const [x, y, right, bottom] = this.binding.region(this.videoFrame);
    this.skinContext.drawImage(
      canvas,
      x,
      y,
      right - x,
      bottom - y,
      0,
      0,
      180,
      180,
    );
    this.renderer.render(
      this.binding.update(this.videoFrame, this.controls),
      this.skin,
    );
    ctx.drawImage(this.surface, x, y, right - x, bottom - y);
    this.paints.push({
      at: performance.now(),
      durationMs: performance.now() - started,
      frame: this.videoFrame,
      controls: Array.from(this.controls),
    });
    if (this.paints.length > 300) this.paints.shift();
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

  dispose() {
    this.running = false;
    cancelAnimationFrame(this.raf);
    this.video.pause();
    this.renderer.dispose();
  }
}
