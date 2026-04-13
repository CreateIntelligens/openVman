import type {
  ClientAudioChunkEvent,
  ServerStreamChunkEvent,
} from "@contracts/generated/typescript/protocol-contracts";
import {
  blobToPcm16Chunks,
  decodeBase64ToArrayBuffer,
  encodeArrayBufferToBase64,
} from "./liveAudioUtils";

type RefLike<T> = { current: T };

type PlaybackRefs = {
  activeSourcesRef: RefLike<Set<AudioBufferSourceNode>>;
  audioContextRef: RefLike<AudioContext | null>;
  isPlayingRef: RefLike<boolean>;
  nextPlaybackTimeRef: RefLike<number>;
  playbackGenerationRef: RefLike<number>;
  playbackQueueRef: RefLike<Promise<void>>;
  playbackUnitsRef: RefLike<number>;
};

type PlaybackCallbacks = {
  onError: (message: string) => void;
  onPlayingChange: (playing: boolean) => void;
};

type PcmChunkOptions = {
  audioContextRef: RefLike<AudioContext | null>;
  blobParts: Blob[];
  chunkBytes: number;
  mimeType: string;
  sampleRate: number;
};

export async function ensureLiveAudioContext(
  audioContextRef: RefLike<AudioContext | null>,
): Promise<AudioContext> {
  if (!audioContextRef.current) {
    const AudioContextCtor = window.AudioContext
      || (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) {
      throw new Error("目前瀏覽器不支援 AudioContext");
    }
    audioContextRef.current = new AudioContextCtor();
  }
  if (audioContextRef.current.state === "suspended") {
    await audioContextRef.current.resume();
  }
  return audioContextRef.current;
}

export function closeLiveAudioContext(
  audioContextRef: RefLike<AudioContext | null>,
  nextPlaybackTimeRef: RefLike<number>,
): void {
  const context = audioContextRef.current;
  audioContextRef.current = null;
  nextPlaybackTimeRef.current = 0;
  if (context) {
    void context.close().catch((reason) => {
      console.warn("Failed to close live audio context:", reason);
    });
  }
}

export function stopLivePlayback(
  refs: PlaybackRefs,
  { onPlayingChange }: Pick<PlaybackCallbacks, "onPlayingChange">,
): void {
  refs.playbackGenerationRef.current += 1;
  refs.playbackQueueRef.current = Promise.resolve();
  refs.playbackUnitsRef.current = 0;
  refs.nextPlaybackTimeRef.current = 0;
  onPlayingChange(false);

  for (const source of refs.activeSourcesRef.current) {
    source.onended = null;
    try {
      source.stop();
    } catch {
      // no-op: a source may already be stopped
    }
    source.disconnect();
  }
  refs.activeSourcesRef.current.clear();
}

export function queueLiveAudioChunk(
  chunk: ServerStreamChunkEvent,
  refs: PlaybackRefs,
  callbacks: PlaybackCallbacks,
): void {
  if (!chunk.audio_base64) {
    return;
  }

  const generation = refs.playbackGenerationRef.current;
  refs.playbackUnitsRef.current += 1;
  if (!refs.isPlayingRef.current) {
    callbacks.onPlayingChange(true);
  }

  refs.playbackQueueRef.current = refs.playbackQueueRef.current
    .then(async () => {
      if (generation !== refs.playbackGenerationRef.current) {
        refs.playbackUnitsRef.current = Math.max(0, refs.playbackUnitsRef.current - 1);
        return;
      }

      const context = await ensureLiveAudioContext(refs.audioContextRef);
      if (generation !== refs.playbackGenerationRef.current) {
        refs.playbackUnitsRef.current = Math.max(0, refs.playbackUnitsRef.current - 1);
        return;
      }

      const audioBuffer = await context.decodeAudioData(decodeBase64ToArrayBuffer(chunk.audio_base64).slice(0));
      const source = context.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(context.destination);
      const startTime = Math.max(context.currentTime, refs.nextPlaybackTimeRef.current);
      refs.nextPlaybackTimeRef.current = startTime + audioBuffer.duration;
      refs.activeSourcesRef.current.add(source);
      source.onended = () => {
        refs.activeSourcesRef.current.delete(source);
        refs.playbackUnitsRef.current = Math.max(0, refs.playbackUnitsRef.current - 1);
        if (refs.playbackUnitsRef.current === 0) {
          refs.nextPlaybackTimeRef.current = 0;
          callbacks.onPlayingChange(false);
        }
      };
      source.start(startTime);
    })
    .catch((reason) => {
      console.error("Failed to play live audio chunk:", reason);
      refs.playbackUnitsRef.current = Math.max(0, refs.playbackUnitsRef.current - 1);
      if (refs.playbackUnitsRef.current === 0) {
        callbacks.onPlayingChange(false);
      }
      callbacks.onError("Live 語音播放失敗");
    });
}

export async function transcodeRecordedBlobsToPcmChunks({
  audioContextRef,
  blobParts,
  chunkBytes,
  mimeType,
  sampleRate,
}: PcmChunkOptions): Promise<ClientAudioChunkEvent[]> {
  const audioContext = await ensureLiveAudioContext(audioContextRef);
  const audioBlob = new Blob(blobParts, { type: mimeType });
  const pcmChunks = await blobToPcm16Chunks(audioBlob, audioContext, sampleRate, chunkBytes);
  return pcmChunks.map((pcmChunk) => ({
    event: "client_audio_chunk",
    audio_base64: encodeArrayBufferToBase64(pcmChunk),
    sample_rate: sampleRate,
    mime_type: `audio/pcm;rate=${sampleRate}`,
    timestamp: Date.now(),
  }));
}

