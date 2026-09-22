import { useCallback, useEffect, useRef, useState } from "react";

import { transcribeOnServer } from "../api/asr";
import { encodeWav } from "../utils/liveAudioUtils";
import { useVad } from "./useVad";

// Silero VAD 固定以 16 kHz 交出取樣。
const VAD_SAMPLE_RATE = 16000;

interface UseVadSpeechRecognitionOptions {
  enabled: boolean;
  onActivity: () => void;
  onError: (message: string) => void;
  onFinalTranscript: (transcript: string) => void;
}

/**
 * 伺服器引擎 + 瀏覽器端 VAD：開著一直聽，講完一句自動上傳轉寫。
 *
 * 伺服器引擎本身沒有斷句，單靠 MediaRecorder 只能做成「按一下錄、再按一下送」。
 * 這裡用本機跑的 Silero VAD 切出每一句，行為就跟瀏覽器內建辨識一致——差別是
 * 聲音只送到自己的後端。VAD 起不來（模型或 WASM 載不到）時 supported 會轉成
 * false，呼叫端要退回按鍵錄音，不能讓使用者因此不能講話。
 */
export function useVadSpeechRecognition({
  enabled,
  onActivity,
  onError,
  onFinalTranscript,
}: UseVadSpeechRecognitionOptions) {
  // 可能同時有好幾句在等後端，用計數而不是布林，否則先回來的那句會把
  // 「辨識中」提早關掉。
  const [pending, setPending] = useState(0);
  const aliveRef = useRef(true);
  const onErrorRef = useRef(onError);
  const onFinalTranscriptRef = useRef(onFinalTranscript);
  useEffect(() => {
    onErrorRef.current = onError;
    onFinalTranscriptRef.current = onFinalTranscript;
  }, [onError, onFinalTranscript]);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const handleAudio = useCallback((samples: Float32Array) => {
    if (!samples.length) return;
    setPending((count) => count + 1);
    void transcribeOnServer(encodeWav(samples, VAD_SAMPLE_RATE), "speech.wav")
      .then((result) => {
        if (!aliveRef.current) return;
        const text = result.text.trim();
        // 連續聆聽時偶爾會切到一段辨識不出東西的雜音，那不是錯誤，安靜略過；
        // 每次都跳錯誤訊息會讓人以為壞了。
        if (!text || text.includes("轉錄失敗")) return;
        onFinalTranscriptRef.current(text);
      })
      .catch((error: unknown) => {
        if (!aliveRef.current) return;
        onErrorRef.current(
          error instanceof Error && error.message
            ? `語音辨識失敗：${error.message}`
            : "語音辨識失敗，請再試一次。",
        );
      })
      .finally(() => {
        if (aliveRef.current) setPending((count) => Math.max(0, count - 1));
      });
  }, []);

  const { speaking, starting, supported } = useVad({
    enabled,
    onSpeechStart: onActivity,
    onAudio: handleAudio,
    // 送出的時機是 onAudio（一句講完）；commit 是給 Live 模式關麥克風用的。
    onSpeechCommit: () => {},
  });

  return { speaking, starting, supported, transcribing: pending > 0 };
}
