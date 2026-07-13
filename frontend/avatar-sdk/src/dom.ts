import { OpenVmanAvatarError } from "./errors";
import type { OpenVmanAvatarOptions } from "./types";

const VENDOR_IDS = ["canvas_video", "canvas_gl", "screen"] as const;

export interface AvatarDom {
  root: HTMLDivElement;
  style: HTMLStyleElement;
}

export function createAvatarDom(options: OpenVmanAvatarOptions): AvatarDom {
  for (const id of VENDOR_IDS) {
    if (document.getElementById(id)) {
      throw new OpenVmanAvatarError(
        "DOM_CONFLICT",
        `The host page already contains #${id}.`,
      );
    }
  }

  const style = document.createElement("style");
  style.dataset.openvmanAvatar = "style";
  style.textContent = `
.openvman-avatar-root {
  background: transparent;
  bottom: 0;
  height: var(--openvman-avatar-height, min(72dvh, 42rem));
  pointer-events: none;
  position: fixed;
  right: 0;
  width: var(--openvman-avatar-width, min(42vw, 28rem));
  z-index: 2147483000;
}
.openvman-avatar-root[data-openvman-contained="true"] {
  height: 100%;
  inset: 0;
  position: absolute;
  width: 100%;
}
.openvman-avatar-root[data-openvman-position="bottom-left"] {
  left: 0;
  right: auto;
}
.openvman-avatar-root #canvas_video {
  background: transparent;
  height: 100%;
  inset: 0;
  object-fit: contain;
  position: absolute;
  width: 100%;
}
.openvman-avatar-root #canvas_gl {
  height: 11.25rem;
  left: 6.25rem;
  opacity: 0.001;
  pointer-events: none;
  position: absolute;
  top: 6.25rem;
  width: 11.25rem;
}
.openvman-avatar-root #screen {
  height: 0.0625rem;
  overflow: hidden;
  position: absolute;
  right: 100%;
  top: 100%;
  width: 0.0625rem;
}
`;

  const root = document.createElement("div");
  root.className = "openvman-avatar-root";
  root.dataset.openvmanAvatar = "root";
  root.dataset.openvmanPosition = options.position ?? "bottom-right";
  root.style.setProperty("--openvman-avatar-height", options.height ?? "");
  root.style.setProperty("--openvman-avatar-width", options.width ?? "");
  if (options.zIndex !== undefined) root.style.zIndex = String(options.zIndex);

  const videoCanvas = document.createElement("canvas");
  videoCanvas.id = "canvas_video";
  videoCanvas.height = 800;
  videoCanvas.width = 800;
  const glCanvas = document.createElement("canvas");
  glCanvas.id = "canvas_gl";
  glCanvas.height = 180;
  glCanvas.width = 180;
  const screen = document.createElement("div");
  screen.id = "screen";
  root.append(videoCanvas, glCanvas, screen);

  const container = options.container ?? document.body;
  if (options.container) {
    root.dataset.openvmanContained = "true";
  }
  document.head.append(style);
  container.append(root);
  return { root, style };
}

export function removeAvatarDom(dom: AvatarDom): void {
  dom.root.remove();
  dom.style.remove();
  window.characterVideo?.remove();
}
