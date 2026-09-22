import { useEffect, useRef, useState } from "react";

import { apiFetch, parseErrorMessage } from "../api/common";
import {
  getAsrErrorMessage,
  VadRecognizer,
  type AsrErrorCode,
  type HttpAdapter,
} from "@shared/speech";

interface UseVadSpeechRecognitionOptions {
  enabled: boolean;
  onActivity: () => void;
  onError: (message: string) => void;
  onFinalTranscript: (transcript: string) => void;
}

const adminHttpAdapter: HttpAdapter = {
  request: (path, init) => apiFetch(path, init),
  parseError: (res) => parseErrorMessage(res),
};

/**
 * 伺服器引擎 + 瀏覽器端 VAD：開著一直聽，講完一句自動上傳轉寫。
 * 薄層轉接：將 React 狀態綁定到底層無框架的 VadRecognizer（continuous 模式）。
 */
export function useVadSpeechRecognition({
  enabled,
  onActivity,
  onError,
  onFinalTranscript,
}: UseVadSpeechRecognitionOptions) {
  const [speaking, setSpeaking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [supported, setSupported] = useState(true);
  const [transcribing, setTranscribing] = useState(false);

  const recognizerRef = useRef<VadRecognizer | null>(null);
  const onErrorRef = useRef(onError);
  const onFinalTranscriptRef = useRef(onFinalTranscript);
  const onActivityRef = useRef(onActivity);

  useEffect(() => {
    onErrorRef.current = onError;
    onFinalTranscriptRef.current = onFinalTranscript;
    onActivityRef.current = onActivity;
  }, [onError, onFinalTranscript, onActivity]);

  if (!recognizerRef.current) {
    recognizerRef.current = new VadRecognizer({
      http: adminHttpAdapter,
      commitMode: "continuous",
      onSpeechStart: () => onActivityRef.current?.(),
      onResult: (text) => onFinalTranscriptRef.current(text),
      onError: (code: AsrErrorCode) => {
        if (code === "vad-unavailable") {
          setSupported(false);
        }
        onErrorRef.current(getAsrErrorMessage(code));
      },
      onSpeakingChange: (val) => setSpeaking(val),
      onStartingChange: (val) => setStarting(val),
      onTranscribingChange: (val) => setTranscribing(val),
    });
  }

  useEffect(() => {
    const recognizer = recognizerRef.current;
    if (!recognizer) return;

    if (enabled) {
      void recognizer.start().then(() => {
        setSupported(recognizer.supported);
      });
    } else {
      recognizer.stop();
    }
  }, [enabled]);

  useEffect(() => {
    return () => {
      recognizerRef.current?.dispose();
      recognizerRef.current = null;
    };
  }, []);

  return { speaking, starting, supported, transcribing };
}
