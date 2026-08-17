const PATCH_SOURCE_SIZE = 180;
const FADE_IN_MS = 200;
const FADE_OUT_MS = 250;
const TAIL_MS = 300;

type ClearRectArgs = [x: number, y: number, width: number, height: number];

interface PendingClear {
  alpha: number;
  args: ClearRectArgs;
}

interface PatchableCanvasContext {
  clearRect(...args: ClearRectArgs): void;
  drawImage(...args: unknown[]): void;
}

export interface IdleLipSyncBypass {
  beginSpeaking(): void;
  endSpeaking(): void;
  resetSpeaking(): void;
  restore(): void;
}

function isFullCanvasClear(
  args: ClearRectArgs,
  canvas: HTMLCanvasElement,
): boolean {
  const [x, y, width, height] = args;
  return x === 0 && y === 0 && width === canvas.width && height === canvas.height;
}

function isLipSyncPatchDraw(args: unknown[], pendingClear: PendingClear): boolean {
  if (args.length !== 9) return false;

  const [x, y, width, height] = pendingClear.args;
  return args[3] === PATCH_SOURCE_SIZE
    && args[4] === PATCH_SOURCE_SIZE
    && args[5] === x
    && args[6] === y
    && args[7] === width
    && args[8] === height;
}

export function installIdleLipSyncBypass(
  canvas = document.getElementById("canvas_video") as HTMLCanvasElement | null,
  now = (): number => performance.now(),
): IdleLipSyncBypass | null {
  const context = canvas?.getContext("2d");
  if (!canvas || !context) return null;

  const patched = context as unknown as PatchableCanvasContext;
  const originalClearRect = patched.clearRect;
  const originalDrawImage = patched.drawImage;
  let pendingClear: PendingClear | null = null;
  let speechStartedAt: number | null = null;
  let speechEndedAt: number | null = null;

  const rawClearRect = (...args: ClearRectArgs): void => {
    originalClearRect.apply(context, args);
  };
  const rawDrawImage = (...args: unknown[]): void => {
    Reflect.apply(originalDrawImage, context, args);
  };
  const flushPendingClear = (): void => {
    if (!pendingClear) return;
    rawClearRect(...pendingClear.args);
    pendingClear = null;
  };
  const patchAlpha = (): number => {
    if (speechStartedAt === null) return 0;

    const currentTime = now();
    const fadeIn = Math.min(1, Math.max(0, (currentTime - speechStartedAt) / FADE_IN_MS));
    if (speechEndedAt === null) return fadeIn;

    const sinceTail = currentTime - speechEndedAt - TAIL_MS;
    if (sinceTail >= FADE_OUT_MS) {
      speechStartedAt = null;
      speechEndedAt = null;
      return 0;
    }
    const fadeOut = sinceTail > 0 ? 1 - sinceTail / FADE_OUT_MS : 1;
    return Math.min(fadeIn, fadeOut);
  };
  const clearRectOverride = (...args: ClearRectArgs): void => {
    if (isFullCanvasClear(args, canvas)) {
      pendingClear = null;
      rawClearRect(...args);
      return;
    }

    // 延後局部 clear，直到下一個 drawImage 證實它確實是嘴型 patch。
    flushPendingClear();
    pendingClear = { alpha: patchAlpha(), args };
  };
  const drawImageOverride = (...args: unknown[]): void => {
    const patchClear = pendingClear;
    if (!patchClear || !isLipSyncPatchDraw(args, patchClear)) {
      flushPendingClear();
      rawDrawImage(...args);
      return;
    }

    pendingClear = null;
    if (patchClear.alpha <= 0) return;
    if (patchClear.alpha >= 1) {
      rawClearRect(...patchClear.args);
      rawDrawImage(...args);
      return;
    }

    const previousAlpha = context.globalAlpha;
    context.globalAlpha = previousAlpha * patchClear.alpha;
    try {
      rawDrawImage(...args);
    } finally {
      context.globalAlpha = previousAlpha;
    }
  };

  patched.clearRect = clearRectOverride;
  patched.drawImage = drawImageOverride;

  return {
    beginSpeaking(): void {
      const currentTime = now();
      const previousFadeOutCompleted = speechEndedAt !== null
        && currentTime - speechEndedAt >= TAIL_MS + FADE_OUT_MS;
      if (speechStartedAt === null || previousFadeOutCompleted) {
        speechStartedAt = currentTime;
      }
      speechEndedAt = null;
    },
    endSpeaking(): void {
      if (speechStartedAt !== null && speechEndedAt === null) {
        speechEndedAt = now();
      }
    },
    resetSpeaking(): void {
      speechStartedAt = null;
      speechEndedAt = null;
    },
    restore(): void {
      flushPendingClear();
      if (patched.clearRect === clearRectOverride) {
        patched.clearRect = originalClearRect;
      }
      if (patched.drawImage === drawImageOverride) {
        patched.drawImage = originalDrawImage;
      }
    },
  };
}
