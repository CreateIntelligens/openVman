import { useEffect, useState, useCallback } from "react";

export type WhisperStatus = "idle" | "loading" | "ready" | "transcribing" | "error";
type WhisperResult = { text?: string } | Array<{ text?: string }>;
type WhisperPipeline = (
  audio: Float32Array,
  options: { language: string; task: "transcribe" },
) => Promise<WhisperResult>;
type ProgressEvent = {
  file?: string;
  progress?: number;
  status?: string;
};

export interface UseWhisperResult {
  status: WhisperStatus;
  loadProgress: number;
  transcribe: (audio: Float32Array) => Promise<string>;
  ensureLoaded: () => Promise<void>;
}

// Module-level state shared across all hook instances to avoid double initialization
let whisperPipelinePromise: Promise<WhisperPipeline> | null = null;
let whisperPipeline: WhisperPipeline | null = null;
let currentStatus: WhisperStatus = "idle";
let currentProgress = 0;

const statusCallbacks = new Set<(status: WhisperStatus) => void>();
const progressCallbacks = new Set<(progress: number) => void>();

export function __resetGlobals() {
  whisperPipelinePromise = null;
  whisperPipeline = null;
  currentStatus = "idle";
  currentProgress = 0;
  statusCallbacks.clear();
  progressCallbacks.clear();
}

function updateStatus(status: WhisperStatus) {
  currentStatus = status;
  statusCallbacks.forEach((callback) => callback(status));
}

function updateProgress(progress: number) {
  currentProgress = progress;
  progressCallbacks.forEach((callback) => callback(progress));
}

function markReady() {
  updateStatus("ready");
  updateProgress(1);
}

function readTranscriptionText(result: WhisperResult): string {
  const firstResult = Array.isArray(result) ? result[0] : result;
  return firstResult?.text || "";
}

export function useWhisper(options?: { enabled?: boolean }): UseWhisperResult {
  const [status, setStatus] = useState<WhisperStatus>(currentStatus);
  const [loadProgress, setLoadProgress] = useState<number>(currentProgress);

  useEffect(() => {
    const onStatusChange = (s: WhisperStatus) => setStatus(s);
    const onProgressChange = (p: number) => setLoadProgress(p);

    statusCallbacks.add(onStatusChange);
    progressCallbacks.add(onProgressChange);

    // Sync initial state
    setStatus(currentStatus);
    setLoadProgress(currentProgress);

    return () => {
      statusCallbacks.delete(onStatusChange);
      progressCallbacks.delete(onProgressChange);
    };
  }, []);

  const ensureLoaded = useCallback(async (): Promise<void> => {
    if (whisperPipeline) {
      markReady();
      return;
    }

    if (whisperPipelinePromise) {
      try {
        await whisperPipelinePromise;
        return;
      } catch {
        // Fall through to retry if last load errored out
      }
    }

    updateStatus("loading");
    updateProgress(0);

    const fileProgresses: Record<string, number> = {};

    const progressCallback = (data: ProgressEvent) => {
      const file = data.file || "model";
      if (data.status === "progress") {
        fileProgresses[file] = data.progress ?? 0;
      } else if (data.status === "ready" || data.status === "done") {
        fileProgresses[file] = 100;
      }

      const files = Object.keys(fileProgresses);
      if (files.length > 0) {
        const totalProgress = files.reduce((acc, fileName) => acc + fileProgresses[fileName], 0);
        updateProgress(totalProgress / files.length / 100);
      }
    };

    whisperPipelinePromise = (async () => {
      try {
        const transformers = await import("@huggingface/transformers");

        // Configure transformers.js environment for local files and WebAssembly
        transformers.env.localModelPath = "/admin/models/";
        transformers.env.allowLocalModels = true;
        transformers.env.allowRemoteModels = false;
        if (transformers.env.backends.onnx.wasm) {
          transformers.env.backends.onnx.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.24.3/dist/";
        }

        const pipe = await transformers.pipeline("automatic-speech-recognition", "whisper-base", {
          progress_callback: progressCallback,
        });

        whisperPipeline = pipe as WhisperPipeline;
        markReady();
        return whisperPipeline;
      } catch (err) {
        console.error("Failed to initialize client-side Whisper ASR model:", err);
        updateStatus("error");
        whisperPipelinePromise = null;
        throw err;
      }
    })();

    await whisperPipelinePromise;
  }, []);

  const transcribe = useCallback(async (audio: Float32Array): Promise<string> => {
    try {
      await ensureLoaded();
      if (!whisperPipeline) {
        throw new Error("ASR model is not initialized");
      }

      updateStatus("transcribing");

      const result = await whisperPipeline(audio, {
        language: "zh",
        task: "transcribe",
      });

      markReady();
      return readTranscriptionText(result);
    } catch (err) {
      console.error("Client-side Whisper transcription failed:", err);
      updateStatus("ready"); // Reset status to ready to prevent UI getting stuck
      return "";
    }
  }, [ensureLoaded]);

  // Pre-load if enabled is true
  useEffect(() => {
    if (options?.enabled && currentStatus === "idle") {
      ensureLoaded().catch(() => {});
    }
  }, [options?.enabled, ensureLoaded]);

  return {
    status,
    loadProgress,
    transcribe,
    ensureLoaded,
  };
}
