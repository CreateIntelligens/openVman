import { useEffect, useRef, useState } from "react";
import { BrowserRecognizer, getAsrErrorMessage, type AsrErrorCode } from "@shared/speech";

interface UseSpeechRecognitionOptions {
  enabled: boolean;
  lang?: string;
  onActivity?: () => void;
  onError?: (message: string) => void;
  onFinalTranscript: (transcript: string) => void;
  onInterimTranscript?: (transcript: string) => void;
}

/**
 * useSpeechRecognition — 薄層轉接：將 React 狀態綁定到底層無框架的 BrowserRecognizer。
 *
 * 支援 continuous 連續聆聽、自動重啟與即時 interimResults。
 */
export function useSpeechRecognition({
  enabled,
  lang = "zh-TW",
  onActivity,
  onError,
  onFinalTranscript,
  onInterimTranscript,
}: UseSpeechRecognitionOptions) {
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [supported, setSupported] = useState(true);

  const recognizerRef = useRef<BrowserRecognizer | null>(null);
  const onErrorRef = useRef(onError);
  const onFinalTranscriptRef = useRef(onFinalTranscript);
  const onInterimTranscriptRef = useRef(onInterimTranscript);
  const onActivityRef = useRef(onActivity);

  useEffect(() => {
    onErrorRef.current = onError;
    onFinalTranscriptRef.current = onFinalTranscript;
    onInterimTranscriptRef.current = onInterimTranscript;
    onActivityRef.current = onActivity;
  }, [onError, onFinalTranscript, onInterimTranscript, onActivity]);

  if (!recognizerRef.current) {
    recognizerRef.current = new BrowserRecognizer({
      lang,
      continuous: true,
      onResult: (text) => onFinalTranscriptRef.current(text),
      onInterim: (text) => onInterimTranscriptRef.current?.(text),
      onSpeechStart: () => onActivityRef.current?.(),
      onError: (code: AsrErrorCode) => {
        if (code === "audio-capture" || code === "not-allowed" || code === "service-not-allowed") {
          setSupported(false);
        }
        onErrorRef.current?.(getAsrErrorMessage(code));
      },
      onListeningChange: (val) => setListening(val),
      onSpeakingChange: (val) => setSpeaking(val),
      onSupportedChange: (val) => setSupported(val),
    });
    setSupported(recognizerRef.current.supported);
  }

  useEffect(() => {
    const recognizer = recognizerRef.current;
    if (!recognizer) return;
    recognizer.updateOptions({ lang });

    if (enabled) {
      recognizer.start();
      setSupported(recognizer.supported);
    } else {
      recognizer.stop();
    }
  }, [enabled, lang]);

  useEffect(() => {
    return () => {
      recognizerRef.current?.dispose();
      recognizerRef.current = null;
    };
  }, []);

  return { listening, speaking, supported };
}
