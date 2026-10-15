/**
 * replySpeechQueue — speaks a streamed reply sentence by sentence, in order.
 *
 * One TTS request runs at a time so audio chunks reach the player in order and
 * playback stays gapless. Sentences that arrive while a request is running are
 * joined into the next request: each request costs about a second before its
 * first audio, so speaking short sentences one by one would leave pauses.
 */

export interface ReplySpeechQueueOptions {
  /** Synthesize one segment and hand its audio to the player; resolves when the TTS response ends. */
  speak: (text: string) => Promise<void>;
}

export function createReplySpeechQueue(options: ReplySpeechQueueOptions) {
  let pending: string[] = [];
  let generation = 0;
  let running: Promise<void> | null = null;

  async function drain(current: number): Promise<void> {
    while (current === generation && pending.length) {
      // 句子保留原本的空白與換行，接起來才跟完整回答一致。
      const segment = pending.join("");
      pending = [];
      if (!segment.trim()) continue;
      try {
        await options.speak(segment);
      } catch {
        // 一段合成失敗不擋後面的句子；錯誤由 speak 自己回報。
      }
    }
    if (current === generation) running = null;
  }

  function push(text: string): void {
    if (!text) return;
    pending.push(text);
    if (!running) running = drain(generation);
  }

  /** Drop queued sentences; the running request is stopped by the caller (TTS cancel). */
  function cancel(): void {
    generation += 1;
    pending = [];
    running = null;
  }

  /** Resolves once every queued sentence has been handed to TTS. */
  function idle(): Promise<void> {
    return running ?? Promise.resolve();
  }

  return { push, cancel, idle };
}
