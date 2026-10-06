import { VAD_SAMPLE_RATE } from "@shared/speech";

import { blobToPcm16Chunks } from "../../utils/liveAudioUtils";

/** 100 ms 一塊，跟前台串流送的大小一樣。 */
const CHUNK_BYTES = (VAD_SAMPLE_RATE / 10) * 2;
// 預設照真實速度送。4 倍速時 Gemini、R2T2 的文字一樣，但 R2T2 要追積壓，講完到定稿
// 多出 2～4 秒，時間就跟實際講話對不上（2026-10-05 實測）；上傳的長檔照真實速度又要
// 乾等整首的長度，所以讓呼叫端選。
const CHUNK_INTERVAL_MS = 100;
/** 尾端補的靜音，讓引擎判斷講完了。 */
const TAIL_SILENCE_CHUNKS = 10;
const READY_TIMEOUT_MS = 10_000;
/** 送完 end 之後最多等多久定稿；定稿之後再靜一下沒新的就收。 */
const FINAL_TIMEOUT_MS = 10_000;
/** R2T2 收到 EOS 一定回最後一則定稿再關線；機器在忙時可能要等十幾秒。 */
const CLOSE_TIMEOUT_MS = 30_000;
const QUIET_AFTER_FINAL_MS = 1_500;
/** 送完 end 時定稿可能早就到齊（Gemini 停頓就定稿），沒新定稿就等這麼久收。 */
const QUIET_AFTER_END_MS = 3_000;

export interface StreamClipResult {
  text: string;
  /** 講完（送完 end）到最後一句定稿的秒數；串流邊講邊辨識，通常接近 0。 */
  elapsedSeconds: number;
}

/**
 * 把一段已錄好的音檔送進串流辨識端點，收齊定稿後回傳整段文字。
 *
 * 後台比較用：串流引擎平常邊講邊送，這裡拿同一段音檔整段送，才能跟批次引擎並排比。
 */
export interface StreamClipOptions {
  /**
   * 等串流端關線才收：R2T2 送完 EOS 後一定回最後一則定稿再關，機器忙時後面幾句會晚到，
   * 用「靜一陣子就收」會把它截掉（2026-10-06 後台實測少了最後三分之一）。
   * Gemini 不會自己關，只能等靜下來。
   */
  waitForClose?: boolean;
  /** 送的倍速；1 是真實速度。 */
  speed?: number;
  /** 邊辨識邊回報目前聽到的字（已定稿的加上講到一半的暫定字幕），給畫面做串流效果。 */
  onPartial?: (text: string) => void;
}

export async function streamClip(
  url: string,
  clip: Blob,
  { waitForClose = false, speed = 1, onPartial }: StreamClipOptions = {},
): Promise<StreamClipResult> {
  const context = new AudioContext();
  let chunks: ArrayBuffer[];
  try {
    chunks = await blobToPcm16Chunks(clip, context, VAD_SAMPLE_RATE, CHUNK_BYTES);
  } finally {
    void context.close().catch(() => {});
  }

  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url);
    socket.binaryType = "arraybuffer";
    const finals: string[] = [];
    let endedAt = 0;
    let lastFinalAt = 0;
    let settled = false;
    let quietTimer: number | undefined;
    const readyTimer = window.setTimeout(() => fail("串流沒有回應"), READY_TIMEOUT_MS);
    let finalTimer: number | undefined;

    function cleanup() {
      window.clearTimeout(readyTimer);
      window.clearTimeout(finalTimer);
      window.clearTimeout(quietTimer);
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) socket.close();
    }

    function done() {
      if (settled) return;
      settled = true;
      cleanup();
      const at = lastFinalAt || performance.now();
      resolve({ text: finals.join(""), elapsedSeconds: endedAt ? Math.max(0, at - endedAt) / 1000 : 0 });
    }

    function fail(message: string) {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new Error(message));
    }

    async function send() {
      for (const chunk of chunks) {
        if (socket.readyState !== WebSocket.OPEN) return;
        socket.send(chunk);
        await new Promise((wait) => window.setTimeout(wait, CHUNK_INTERVAL_MS / speed));
      }
      const silence = new ArrayBuffer(CHUNK_BYTES);
      for (let i = 0; i < TAIL_SILENCE_CHUNKS && socket.readyState === WebSocket.OPEN; i++) {
        socket.send(silence);
        await new Promise((wait) => window.setTimeout(wait, CHUNK_INTERVAL_MS / speed));
      }
      if (socket.readyState !== WebSocket.OPEN) return;
      socket.send(JSON.stringify({ type: "end" }));
      endedAt = performance.now();
      if (waitForClose) {
        finalTimer = window.setTimeout(done, CLOSE_TIMEOUT_MS);
        return;
      }
      finalTimer = window.setTimeout(done, FINAL_TIMEOUT_MS);
      quietTimer = window.setTimeout(done, QUIET_AFTER_END_MS);
    }

    socket.onmessage = (event) => {
      let data: { type?: string; text?: string; code?: string };
      try {
        data = JSON.parse(String(event.data));
      } catch {
        return;
      }
      if (data.type === "ready") {
        window.clearTimeout(readyTimer);
        void send();
      } else if (data.type === "interim" && data.text) {
        onPartial?.(finals.join("") + data.text);
      } else if (data.type === "final" && data.text) {
        finals.push(data.text);
        onPartial?.(finals.join(""));
        lastFinalAt = performance.now();
        if (endedAt && !waitForClose) {
          window.clearTimeout(quietTimer);
          quietTimer = window.setTimeout(done, QUIET_AFTER_FINAL_MS);
        }
      } else if (data.type === "error") {
        fail(data.code === "not_configured" ? "這個串流引擎沒有設定" : "串流辨識失敗");
      }
    };
    socket.onerror = () => fail("串流連不上");
    socket.onclose = () => (endedAt ? done() : fail("串流中斷"));
  });
}
