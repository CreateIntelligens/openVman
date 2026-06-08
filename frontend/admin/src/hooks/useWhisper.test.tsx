import { renderHook, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useWhisper, __resetGlobals } from "./useWhisper";

// Mock @huggingface/transformers
const mockPipeline = vi.fn();
vi.mock("@huggingface/transformers", () => ({
  pipeline: (...args: any[]) => mockPipeline(...args),
  env: {
    localModelPath: "",
    allowLocalFiles: false,
    allowRemoteModels: true,
    backends: {
      onnx: {
        wasm: {
          wasmPaths: "",
        },
      },
    },
  },
}));

describe("useWhisper hook", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    __resetGlobals();
  });

  it("initializes with idle status and progress 0", () => {
    const { result } = renderHook(() => useWhisper());
    expect(result.current.status).toBe("idle");
    expect(result.current.loadProgress).toBe(0);
  });

  it("loads model and updates status to ready on ensureLoaded", async () => {
    mockPipeline.mockResolvedValue(() => ({ text: "test transcription" }));
    const { result } = renderHook(() => useWhisper());

    await act(async () => {
      await result.current.ensureLoaded();
    });

    expect(result.current.status).toBe("ready");
    expect(result.current.loadProgress).toBe(1.0);
    expect(mockPipeline).toHaveBeenCalledWith("automatic-speech-recognition", "whisper-base", expect.any(Object));
  });

  it("transcribes audio data successfully", async () => {
    const mockTranscribeFn = vi.fn().mockResolvedValue({ text: "哈囉你好" });
    mockPipeline.mockResolvedValue(mockTranscribeFn);

    const { result } = renderHook(() => useWhisper());

    await act(async () => {
      await result.current.ensureLoaded();
    });

    const audio = new Float32Array(16000);
    let transcription = "";
    await act(async () => {
      transcription = await result.current.transcribe(audio);
    });

    expect(transcription).toBe("哈囉你好");
    expect(mockTranscribeFn).toHaveBeenCalledWith(audio, {
      language: "zh",
      task: "transcribe",
    });
  });
});
