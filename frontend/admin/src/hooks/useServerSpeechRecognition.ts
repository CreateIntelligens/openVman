import { useCallback, useEffect, useRef, useState } from "react";

import { transcribeOnServer } from "../api/asr";

interface UseServerSpeechRecognitionOptions {
  /** true 開始錄音；轉回 false 時停止並把整段送去轉寫。 */
  enabled: boolean;
  onError: (message: string) => void;
  onFinalTranscript: (transcript: string) => void;
}

// MediaRecorder 的容器格式依瀏覽器而異；後端用副檔名決定怎麼解，所以要把
// 實際用的格式對應成正確的副檔名，不能一律寫死 .webm。
const MIME_SUFFIXES: Array<[string, string]> = [
  ["audio/webm", ".webm"],
  ["audio/ogg", ".ogg"],
  ["audio/mp4", ".mp4"],
];

function suffixFor(mimeType: string): string {
  const found = MIME_SUFFIXES.find(([type]) => mimeType.startsWith(type));
  return found ? found[1] : ".webm";
}

/**
 * 伺服器引擎的語音輸入：錄一段、整段上傳、由後端依帳號選定的引擎轉寫。
 *
 * 對外介面刻意跟 useSpeechRecognition 一致（enabled 進、transcript 出），呼叫端
 * 依引擎擇一啟用即可。差別在行為：瀏覽器辨識是連續聆聽、邊講邊出字；這個
 * 沒有中途結果，使用者按停才開始辨識，所以多一個 transcribing 狀態給畫面用。
 */
export function useServerSpeechRecognition({
  enabled,
  onError,
  onFinalTranscript,
}: UseServerSpeechRecognitionOptions) {
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const supported = typeof MediaRecorder !== "undefined";

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  // 卸載後才回來的轉寫結果不該再送進聊天室。
  const aliveRef = useRef(true);
  const onErrorRef = useRef(onError);
  const onFinalTranscriptRef = useRef(onFinalTranscript);
  useEffect(() => {
    onErrorRef.current = onError;
    onFinalTranscriptRef.current = onFinalTranscript;
  }, [onError, onFinalTranscript]);

  const releaseStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const send = useCallback(async (clip: Blob, mimeType: string) => {
    setTranscribing(true);
    try {
      const result = await transcribeOnServer(clip, `speech${suffixFor(mimeType)}`);
      if (!aliveRef.current) return;
      const text = result.text.trim();
      // 後端轉寫失敗時回的是「（音訊轉錄失敗）」，那幾個字不該被當成使用者
      // 說的話送出去。
      if (!text || text.includes("轉錄失敗")) {
        onErrorRef.current("語音辨識失敗，請再試一次。");
        return;
      }
      onFinalTranscriptRef.current(text);
    } catch (error) {
      if (!aliveRef.current) return;
      onErrorRef.current(
        error instanceof Error && error.message
          ? `語音辨識失敗：${error.message}`
          : "語音辨識失敗，請再試一次。",
      );
    } finally {
      if (aliveRef.current) setTranscribing(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    if (!supported) {
      onErrorRef.current("此瀏覽器不支援錄音。");
      return;
    }

    let cancelled = false;
    void (async () => {
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch {
        // 使用者拒絕權限或裝置上根本沒有麥克風，兩者都要等這裡才知道。
        if (!cancelled) onErrorRef.current("無法使用麥克風，請確認瀏覽器權限。");
        return;
      }
      if (cancelled) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      try {
        const mimeType = MIME_SUFFIXES
          .map(([type]) => type)
          .find((type) => MediaRecorder.isTypeSupported(type)) ?? "";
        // 位元率釘 128 kbps：實測 opus 壓到 24 kbps 時辨識會崩壞。
        const recorder = new MediaRecorder(stream, {
          ...(mimeType ? { mimeType } : {}),
          audioBitsPerSecond: 128_000,
        });
        const chunks: Blob[] = [];
        recorder.ondataavailable = (event) => {
          if (event.data.size) chunks.push(event.data);
        };
        recorder.onstop = () => {
          releaseStream();
          const type = recorder.mimeType || mimeType || "audio/webm";
          const clip = new Blob(chunks, { type });
          if (!aliveRef.current) return;
          if (!clip.size) {
            onErrorRef.current("沒有錄到聲音。");
            return;
          }
          void send(clip, type);
        };
        recorderRef.current = recorder;
        recorder.start();
        setRecording(true);
      } catch {
        releaseStream();
        onErrorRef.current("無法開始錄音。");
      }
    })();

    // enabled 轉 false（使用者按停、或閒置逾時）走這裡：stop() 觸發 onstop，
    // 音檔在那裡才送出。
    return () => {
      cancelled = true;
      const recorder = recorderRef.current;
      recorderRef.current = null;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      else releaseStream();
      setRecording(false);
    };
  }, [enabled, releaseStream, send, supported]);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  return { recording, supported, transcribing };
}
