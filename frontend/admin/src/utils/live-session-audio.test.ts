import { describe, expect, it, vi } from "vitest";

import { queueLiveAudioChunk } from "./live-session-audio";

function makeContext() {
  const buffer = { duration: 0.5, sampleRate: 16000, length: 8000, numberOfChannels: 1 } as unknown as AudioBuffer;
  const source = { buffer: null as AudioBuffer | null, connect: vi.fn(), start: vi.fn(), onended: null as null | (() => void) };
  const context = {
    state: "running",
    currentTime: 0,
    destination: { id: "destination" },
    decodeAudioData: vi.fn().mockResolvedValue(buffer),
    createBufferSource: () => source,
    resume: vi.fn(),
  } as unknown as AudioContext;
  return { context, source, buffer };
}

function makeRefs(context: AudioContext, outputNode: AudioNode | null) {
  return {
    activeSourcesRef: { current: new Set<AudioBufferSourceNode>() },
    audioContextRef: { current: context },
    isPlayingRef: { current: false },
    nextPlaybackTimeRef: { current: 0 },
    outputNodeRef: { current: outputNode },
    playbackGenerationRef: { current: 0 },
    playbackQueueRef: { current: Promise.resolve() },
    playbackUnitsRef: { current: 0 },
  };
}

describe("queueLiveAudioChunk", () => {
  it("hands the decoded chunk to the mascot hook and routes playback through the output node", async () => {
    const { context, source, buffer } = makeContext();
    const analyser = { id: "analyser" } as unknown as AudioNode;
    const refs = makeRefs(context, analyser);
    const onDecodedChunk = vi.fn();

    queueLiveAudioChunk(
      { event: "server_stream_chunk", text: "", audio_base64: "AAAA" } as never,
      refs,
      { onError: vi.fn(), onPlayingChange: vi.fn(), onDecodedChunk },
    );
    await refs.playbackQueueRef.current;

    expect(onDecodedChunk).toHaveBeenCalledWith(buffer, context);
    expect(source.connect).toHaveBeenCalledWith(analyser);
    expect(source.start).toHaveBeenCalled();
  });

  it("falls back to the destination when no output node is set", async () => {
    const { context, source } = makeContext();
    const refs = makeRefs(context, null);

    queueLiveAudioChunk(
      { event: "server_stream_chunk", text: "", audio_base64: "AAAA" } as never,
      refs,
      { onError: vi.fn(), onPlayingChange: vi.fn() },
    );
    await refs.playbackQueueRef.current;

    expect(source.connect).toHaveBeenCalledWith(context.destination);
  });
});
