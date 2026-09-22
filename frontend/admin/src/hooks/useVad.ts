import { useCallback, useEffect, useRef, useState } from "react";

const VAD_ASSET_BASE = "/admin/vad/";
const ORT_WASM_CDN = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.24.3/dist/";
const SILENCE_TIMEOUT_MS = 1000;

type VadInstance = {
  destroy: () => Promise<void>;
  start: () => Promise<void>;
  pause: () => Promise<void>;
};

type VadCallbacks = {
  onSpeechStart: () => void;
  onSpeechEnd: (audio: Float32Array) => void;
  onVADMisfire: () => void;
};

interface UseVadOptions {
  /** Called when speech ends and silence timeout has passed */
  onSpeechCommit: () => void;
  /** Called when speech activity starts */
  onSpeechStart?: () => void;
  /** Exposes the audio buffer array when speech ends */
  onAudio?: (audio: Float32Array) => void;
  /** Whether VAD is enabled (mic open) */
  enabled: boolean;
}

/**
 * 實例跨次開關重用：載套件、抓 WASM 與模型、建 worklet 只做一次，之後每次開關
 * 只剩 pause()/start()——pause 會放掉麥克風軌（瀏覧器的錄音指示會熄），start 再
 * 要回來，模型不必重載。每次都 destroy 再 new 的話，第一次要一兩秒、之後也要幾
 * 百毫秒，使用者開頭說的那幾個字都收不到。
 *
 * starting 是「按下去到真的開始收音」那段：這段期間說的話收不到，畫面要照實
 * 顯示，不能假裝已經在聽。
 */
export function useVad({ onSpeechCommit, onSpeechStart, onAudio, enabled }: UseVadOptions) {
  const [speaking, setSpeaking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [supported, setSupported] = useState(true);
  const instanceRef = useRef<Promise<VadInstance> | null>(null);
  // 回呼看的是「現在這一輪」，實例只建一次，所以透過這層轉接而不是綁死。
  const callbacksRef = useRef<VadCallbacks>({
    onSpeechStart: () => {},
    onSpeechEnd: () => {},
    onVADMisfire: () => {},
  });
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onSpeechCommitRef = useRef(onSpeechCommit);
  onSpeechCommitRef.current = onSpeechCommit;
  const onSpeechStartRef = useRef(onSpeechStart);
  onSpeechStartRef.current = onSpeechStart;
  const onAudioRef = useRef(onAudio);
  onAudioRef.current = onAudio;

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const loadInstance = useCallback((): Promise<VadInstance> => {
    if (instanceRef.current) return instanceRef.current;
    const pending = (async () => {
      const { MicVAD } = await import("@ricky0123/vad-web");
      return await MicVAD.new({
        baseAssetPath: VAD_ASSET_BASE,
        onnxWASMBasePath: ORT_WASM_CDN,
        model: "v5",
        // 載好先不要開麥克風：由 enabled 決定，否則關得太快會跟載入賽跑。
        startOnLoad: false,
        onSpeechStart: () => callbacksRef.current.onSpeechStart(),
        onSpeechEnd: (audio: Float32Array) => callbacksRef.current.onSpeechEnd(audio),
        onVADMisfire: () => callbacksRef.current.onVADMisfire(),
      }) as VadInstance;
    })();
    instanceRef.current = pending;
    pending.catch(() => {
      instanceRef.current = null;
    });
    return pending;
  }, []);

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    setStarting(true);

    callbacksRef.current = {
      onSpeechStart: () => {
        if (cancelled) return;
        setSpeaking(true);
        clearSilenceTimer();
        onSpeechStartRef.current?.();
      },
      onSpeechEnd: (audio) => {
        if (cancelled) return;
        setSpeaking(false);
        clearSilenceTimer();
        onAudioRef.current?.(audio);
        silenceTimerRef.current = setTimeout(() => {
          onSpeechCommitRef.current();
        }, SILENCE_TIMEOUT_MS);
      },
      onVADMisfire: () => {
        if (cancelled) return;
        setSpeaking(false);
      },
    };

    void (async () => {
      let instance: VadInstance;
      try {
        instance = await loadInstance();
        if (cancelled) return;
        await instance.start();
      } catch (error) {
        console.warn("VAD initialization failed:", error);
        if (!cancelled) setSupported(false);
        return;
      } finally {
        if (!cancelled) setStarting(false);
      }
      // 開始收音後才發現這一輪已經被關掉：麥克風要放回去。
      if (cancelled) void instance.pause().catch(() => {});
    })();

    return () => {
      cancelled = true;
      clearSilenceTimer();
      setSpeaking(false);
      setStarting(false);
      // pause 而不是 destroy：麥克風放掉，模型留著給下一次。
      void instanceRef.current?.then((instance) => instance.pause()).catch(() => {});
    };
  }, [enabled, clearSilenceTimer, loadInstance]);

  // 只有整個元件卸載才 destroy。
  useEffect(() => () => {
    const pending = instanceRef.current;
    instanceRef.current = null;
    void pending?.then((instance) => instance.destroy()).catch(() => {});
  }, []);

  return { speaking, starting, supported };
}
