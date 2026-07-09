import { useCallback, useEffect, useRef, useState } from "react";

type SpeechRecognitionAlternativeLike = {
  transcript?: string;
};

type SpeechRecognitionResultLike = {
  isFinal: boolean;
  [index: number]: SpeechRecognitionAlternativeLike | undefined;
};

type SpeechRecognitionResultListLike = {
  length: number;
  [index: number]: SpeechRecognitionResultLike | undefined;
};

type SpeechRecognitionEventLike = {
  resultIndex?: number;
  results: SpeechRecognitionResultListLike;
};

type SpeechRecognitionErrorEventLike = {
  error?: string;
  message?: string;
};

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onspeechstart: (() => void) | null;
  onspeechend: (() => void) | null;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

type SpeechRecognitionWindow = Window & {
  SpeechRecognition?: SpeechRecognitionConstructor;
  webkitSpeechRecognition?: SpeechRecognitionConstructor;
};

interface UseSpeechRecognitionOptions {
  enabled: boolean;
  lang?: string;
  onActivity?: () => void;
  onError?: (message: string) => void;
  onFinalTranscript: (transcript: string) => void;
}

function getSpeechRecognitionCtor(): SpeechRecognitionConstructor | null {
  const speechWindow = window as SpeechRecognitionWindow;
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null;
}

function readFinalTranscript(event: SpeechRecognitionEventLike): string {
  const transcripts: string[] = [];
  const startIndex = event.resultIndex ?? 0;

  for (let index = startIndex; index < event.results.length; index += 1) {
    const result = event.results[index];
    if (result?.isFinal) {
      const transcript = result[0]?.transcript?.trim();
      if (transcript) transcripts.push(transcript);
    }
  }

  return transcripts.join(" ");
}

function isTerminalSpeechError(error?: string): boolean {
  return error === "audio-capture"
    || error === "not-allowed"
    || error === "service-not-allowed";
}

export function useSpeechRecognition({
  enabled,
  lang = "zh-TW",
  onActivity,
  onError,
  onFinalTranscript,
}: UseSpeechRecognitionOptions) {
  const [supported, setSupported] = useState(() => getSpeechRecognitionCtor() !== null);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const enabledRef = useRef(enabled);
  const onActivityRef = useRef(onActivity);
  const onErrorRef = useRef(onError);
  const onFinalTranscriptRef = useRef(onFinalTranscript);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    enabledRef.current = enabled;
  }, [enabled]);

  useEffect(() => {
    onActivityRef.current = onActivity;
    onErrorRef.current = onError;
    onFinalTranscriptRef.current = onFinalTranscript;
  }, [onActivity, onError, onFinalTranscript]);

  const stopRecognition = useCallback(() => {
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    if (!recognition) return;

    recognition.onstart = null;
    recognition.onend = null;
    recognition.onerror = null;
    recognition.onresult = null;
    recognition.onspeechstart = null;
    recognition.onspeechend = null;

    try {
      recognition.abort();
    } catch {
      recognition.stop();
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      stopRecognition();
      return;
    }

    const RecognitionCtor = getSpeechRecognitionCtor();
    if (!RecognitionCtor) {
      setSupported(false);
      setListening(false);
      setSpeaking(false);
      return;
    }

    setSupported(true);

    let cancelled = false;
    let shouldRestart = true;
    const recognition = new RecognitionCtor();
    recognitionRef.current = recognition;
    recognition.lang = lang;
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    const startRecognition = (): void => {
      if (cancelled || !enabledRef.current) return;

      try {
        recognition.start();
      } catch {
        shouldRestart = false;
        setListening(false);
        onErrorRef.current?.("語音輸入無法啟動");
      }
    };

    recognition.onstart = () => {
      if (cancelled) return;
      setListening(true);
      onActivityRef.current?.();
    };

    recognition.onspeechstart = () => {
      if (cancelled) return;
      setSpeaking(true);
      onActivityRef.current?.();
    };

    recognition.onspeechend = () => {
      if (cancelled) return;
      setSpeaking(false);
    };

    recognition.onresult = (event) => {
      if (cancelled) return;
      onActivityRef.current?.();

      const transcript = readFinalTranscript(event);
      if (transcript) {
        onFinalTranscriptRef.current(transcript);
      }
    };

    recognition.onerror = (event) => {
      if (cancelled) return;
      setSpeaking(false);

      if (isTerminalSpeechError(event.error)) {
        shouldRestart = false;
        setSupported(false);
        onErrorRef.current?.("瀏覽器無法使用語音輸入");
      } else if (event.error !== "aborted" && event.error !== "no-speech") {
        onErrorRef.current?.("語音輸入中斷");
      }
    };

    recognition.onend = () => {
      if (cancelled) return;
      setListening(false);
      setSpeaking(false);

      if (enabledRef.current && shouldRestart) {
        window.setTimeout(startRecognition, 0);
      }
    };

    startRecognition();

    return () => {
      cancelled = true;
      shouldRestart = false;
      stopRecognition();
      setListening(false);
      setSpeaking(false);
    };
  }, [enabled, lang, stopRecognition]);

  return { listening, speaking, supported };
}
