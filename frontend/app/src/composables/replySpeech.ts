/**
 * replySpeech — speaks each reply with one TTS request.
 *
 * Streamed sentences are collected, not spoken: the reply is synthesized once
 * when it is complete. Speaking sentence by sentence made the next segment wait
 * for the previous download, so a short first sentence left a gap, and each
 * segment came out in its own tone. TTS first audio does not depend on text
 * length, so a whole reply only waits for the remaining sentences to arrive.
 */

export interface ReplySpeechOptions {
  /** Synthesize the reply and hand its audio to the player; resolves when the TTS response ends. */
  speak: (text: string) => Promise<void>;
  /**
   * True from the first collected sentence until this reply's TTS response ends;
   * false when there is nothing to say or the reply is dropped. A cancelled
   * reply that settles late never reports, so it cannot clear a newer reply's state.
   */
  onWaiting?: (waiting: boolean) => void;
}

export function createReplySpeech(options: ReplySpeechOptions) {
  let collected = "";
  let generation = 0;
  let running: Promise<void> | null = null;

  function setWaiting(waiting: boolean): void {
    options.onWaiting?.(waiting);
  }

  /** Speak a complete reply now. */
  function speak(text: string): void {
    collected = "";
    generation += 1;
    const current = generation;
    if (!text.trim()) {
      running = null;
      setWaiting(false);
      return;
    }
    setWaiting(true);
    // 失敗由 speak 自己回報；這裡只負責記錄是否還在念。
    running = options.speak(text)
      .catch(() => undefined)
      .finally(() => {
        if (current !== generation) return;
        running = null;
        setWaiting(false);
      });
  }

  /** A streamed sentence: kept until `finish`, so nothing is synthesized yet. */
  function collect(text: string): void {
    if (!text) return;
    collected += text;
    setWaiting(true);
  }

  /**
   * The reply is complete: speak the final text. Falls back to the collected
   * sentences only when the final text is empty; when the model rewrote its
   * answer mid-stream, sentences it took back are not in the final text.
   */
  function finish(finalText: string): void {
    speak(finalText.trim() ? finalText : collected);
  }

  /** Drop collected sentences; the running request is stopped by the caller (TTS cancel). */
  function cancel(): void {
    generation += 1;
    collected = "";
    running = null;
    setWaiting(false);
  }

  /** Resolves once the current reply has been handed to TTS and its response ended. */
  function idle(): Promise<void> {
    return running ?? Promise.resolve();
  }

  return { speak, collect, finish, cancel, idle };
}
