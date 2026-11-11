/**
 * useAudioPlayer — PCM playback with an optional shared avatar audio owner.
 *
 * Accepts raw PCM chunks (16 kHz, mono, 16-bit LE — either binary or base64),
 * Avatar callers delegate playback and inference to one shared engine clock.
 * Other callers retain the generic PCM scheduler.
 */
import { ref, readonly, onUnmounted } from "vue";
import { PcmScheduler } from "@shared/speech";

interface AudioPlayerOptions {
  engine?: {
    pushAudio(pcm: Int16Array): Promise<void>;
    finishAudio(): Promise<void>;
    prepareAudio(): Promise<void>;
    clearAudio(): void;
    subscribePlayback(listener: (state: string) => void): () => void;
  };
  /** Callback to push PCM to WASM lip-sync engine */
  onPcmChunk?: (pcm: Int16Array) => void;
  /** Called with the current output volume while audio is playing */
  onPlaybackVolume?: (volume: number) => void;
  /** Called when the entire queued audio finishes playing */
  onPlaybackEnd?: () => void;
  /** Called when the first source in a playback queue is scheduled */
  onPlaybackStart?: () => void;
  /** Called when playback is stopped before the queue drains naturally */
  onPlaybackReset?: () => void;
  /** Called when the audio queue drains (last scheduled chunk has played) */
  onQueueEmpty?: () => void;
  /** Called when a chunk is dropped due to a decode/scheduling error */
  onChunkDropped?: (reason: string) => void;
}

export function useAudioPlayer(options: AudioPlayerOptions = {}) {
  if (options.engine) return useEngineAudio(options, options.engine);
  const isPlaying = ref(false);

  const scheduler = new PcmScheduler({
    sampleRate: 16000,
    onPcmChunk: options.onPcmChunk,
    onPlaybackVolume: options.onPlaybackVolume,
    onPlaybackStart: () => {
      isPlaying.value = true;
      options.onPlaybackStart?.();
    },
    onPlaybackEnd: () => {
      isPlaying.value = false;
      options.onPlaybackEnd?.();
    },
    onPlaybackReset: () => {
      isPlaying.value = false;
      options.onPlaybackReset?.();
    },
    onQueueEmpty: () => {
      isPlaying.value = false;
      options.onQueueEmpty?.();
    },
    onChunkDropped: options.onChunkDropped,
  });

  async function playChunk(data: ArrayBuffer | string): Promise<void> {
    await scheduler.playChunk(data);
    isPlaying.value = scheduler.isPlaying;
  }

  function stopAll(): void {
    scheduler.stopAll();
    isPlaying.value = false;
  }

  function resetSchedule(): void {
    scheduler.resetSchedule();
  }

  function flush(): void {
    scheduler.flush();
    isPlaying.value = false;
  }

  async function resumeContext(): Promise<void> {
    await scheduler.resumeContext();
  }

  onUnmounted(() => {
    scheduler.dispose();
  });

  return {
    isPlaying: readonly(isPlaying),
    playChunk,
    stopAll,
    resetSchedule,
    flush,
    resumeContext,
    finish: async () => {},
  };
}

/** Avatar playback uses the engine's sample clock; the generic scheduler remains for other audio. */
function useEngineAudio(
  options: AudioPlayerOptions,
  engine: NonNullable<AudioPlayerOptions["engine"]>,
) {
  const isPlaying = ref(false);
  let started = false;
  let idleTimer: ReturnType<typeof setTimeout> | null = null;
  let generation = 0;
  let inputRevision = 0;
  const unsubscribe = engine.subscribePlayback((state) => {
    const active = ["buffering", "playing", "rebuffering", "draining"].includes(
      state,
    );
    isPlaying.value = active;
    if (state === "playing" && !started) {
      started = true;
      options.onPlaybackStart?.();
    }
    if ((state === "ready" || state === "error") && started) {
      started = false;
      options.onPlaybackEnd?.();
      options.onQueueEmpty?.();
    }
  });
  const cancelTimer = () => {
    if (idleTimer !== null) clearTimeout(idleTimer);
    idleTimer = null;
  };
  const finish = () => {
    inputRevision++;
    cancelTimer();
    return engine.finishAudio();
  };
  async function playChunk(data: ArrayBuffer | string): Promise<void> {
    const revision = generation;
    const input = ++inputRevision;
    cancelTimer();
    let pcm: Int16Array;
    if (typeof data === "string") {
      const raw = atob(data);
      const bytes = Uint8Array.from(raw, (c) => c.charCodeAt(0));
      pcm = new Int16Array(bytes.buffer);
    } else pcm = new Int16Array(data.slice(0));
    try {
      await engine.pushAudio(pcm);
      if (revision !== generation || input !== inputRevision) return;
      idleTimer = setTimeout(() => {
        idleTimer = null;
        if (revision === generation)
          void finish().catch((error) => {
            if (revision === generation)
              options.onChunkDropped?.(String(error));
          });
      }, 180);
    } catch (error) {
      if (revision !== generation) return;
      options.onChunkDropped?.(String(error));
      throw error;
    }
  }
  const stopAll = () => {
    generation++;
    cancelTimer();
    started = false;
    engine.clearAudio();
    isPlaying.value = false;
    options.onPlaybackReset?.();
  };
  onUnmounted(() => {
    stopAll();
    unsubscribe();
  });
  return {
    isPlaying: readonly(isPlaying),
    playChunk,
    stopAll,
    resetSchedule: stopAll,
    flush: stopAll,
    resumeContext: engine.prepareAudio,
    finish,
  };
}
