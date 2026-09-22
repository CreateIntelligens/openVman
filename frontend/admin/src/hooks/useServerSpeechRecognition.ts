import { useEffect, useRef, useState } from "react";

import { apiFetch, parseErrorMessage } from "../api/common";
import {
  getAsrErrorMessage,
  ServerRecorder,
  type AsrErrorCode,
  type HttpAdapter,
} from "@shared/speech";

interface UseServerSpeechRecognitionOptions {
  /** true 開始錄音；轉回 false 時停止並把整段送去轉寫。 */
  enabled: boolean;
  onError: (message: string) => void;
  onFinalTranscript: (transcript: string) => void;
}

const adminHttpAdapter: HttpAdapter = {
  request: (path, init) => apiFetch(path, init),
  parseError: (res) => parseErrorMessage(res),
};

/**
 * 伺服器引擎的語音輸入：錄一段、整段上傳、由後端依帳號選定的引擎轉寫。
 * 薄層轉接：將 React state 與生命週期綁定至共用的 ServerRecorder 核心。
 */
export function useServerSpeechRecognition({
  enabled,
  onError,
  onFinalTranscript,
}: UseServerSpeechRecognitionOptions) {
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);

  const recorderRef = useRef<ServerRecorder | null>(null);
  const onErrorRef = useRef(onError);
  const onFinalTranscriptRef = useRef(onFinalTranscript);

  useEffect(() => {
    onErrorRef.current = onError;
    onFinalTranscriptRef.current = onFinalTranscript;
  }, [onError, onFinalTranscript]);

  if (!recorderRef.current) {
    recorderRef.current = new ServerRecorder({
      http: adminHttpAdapter,
      onResult: (text) => onFinalTranscriptRef.current(text),
      onError: (code: AsrErrorCode) => onErrorRef.current(getAsrErrorMessage(code)),
      onRecordingChange: (val) => setRecording(val),
      onTranscribingChange: (val) => setTranscribing(val),
    });
  }

  const supported = recorderRef.current.supported;

  useEffect(() => {
    const recorder = recorderRef.current;
    if (!recorder) return;

    if (enabled) {
      void recorder.start();
    } else {
      recorder.stop();
    }
  }, [enabled]);

  useEffect(() => {
    return () => {
      recorderRef.current?.dispose();
      recorderRef.current = null;
    };
  }, []);

  return { recording, supported, transcribing };
}
