import { useCallback, useEffect, useRef, useState } from "react";

const VAD_ASSET_BASE = "/admin/vad/";
const ORT_WASM_CDN = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.24.3/dist/";
const SILENCE_TIMEOUT_MS = 1000;

interface UseVadOptions {
  /** Called when speech ends and silence timeout has passed */
  onSpeechCommit: () => void;
  /** Called when speech activity starts */
  onSpeechStart?: () => void;
  /** Whether VAD is enabled (mic open) */
  enabled: boolean;
}

export function useVad({ onSpeechCommit, onSpeechStart, enabled }: UseVadOptions) {
  const [speaking, setSpeaking] = useState(false);
  const [supported, setSupported] = useState(true);
  const vadRef = useRef<{ destroy: () => Promise<void>; start: () => Promise<void>; pause: () => Promise<void> } | null>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onSpeechCommitRef = useRef(onSpeechCommit);
  onSpeechCommitRef.current = onSpeechCommit;
  const onSpeechStartRef = useRef(onSpeechStart);
  onSpeechStartRef.current = onSpeechStart;

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const cleanup = useCallback(() => {
    clearSilenceTimer();
    setSpeaking(false);
    const vad = vadRef.current;
    if (vad) {
      vadRef.current = null;
      vad.destroy().catch(() => {});
    }
  }, [clearSilenceTimer]);

  useEffect(() => {
    if (!enabled) {
      cleanup();
      return;
    }

    let cancelled = false;

    async function init() {
      try {
        const { MicVAD } = await import("@ricky0123/vad-web");
        if (cancelled) return;

        const vad = await MicVAD.new({
          baseAssetPath: VAD_ASSET_BASE,
          onnxWASMBasePath: ORT_WASM_CDN,
          model: "v5",
          startOnLoad: true,
          onSpeechStart: () => {
            if (cancelled) return;
            setSpeaking(true);
            clearSilenceTimer();
            onSpeechStartRef.current?.();
          },
          onSpeechEnd: () => {
            if (cancelled) return;
            setSpeaking(false);
            clearSilenceTimer();
            silenceTimerRef.current = setTimeout(() => {
              onSpeechCommitRef.current();
            }, SILENCE_TIMEOUT_MS);
          },
          onVADMisfire: () => {
            if (cancelled) return;
            setSpeaking(false);
          },
        });

        if (cancelled) {
          await vad.destroy();
          return;
        }

        vadRef.current = vad;
      } catch (error) {
        console.warn("VAD initialization failed:", error);
        if (!cancelled) setSupported(false);
      }
    }

    init();

    return () => {
      cancelled = true;
      cleanup();
    };
  }, [enabled, cleanup, clearSilenceTimer]);

  return { speaking, supported };
}
