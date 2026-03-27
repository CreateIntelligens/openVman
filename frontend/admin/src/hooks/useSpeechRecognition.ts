import { useCallback, useEffect, useRef, useState } from "react";

export function useSpeechRecognition(onResult: (transcript: string) => void) {
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const restartingRef = useRef(false);
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;

  const supported = typeof window !== "undefined" && ("SpeechRecognition" in window || "webkitSpeechRecognition" in window);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  const startFresh = useCallback(() => {
    if (!supported) return;

    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new Ctor();
    recognition.lang = "zh-TW";
    recognition.interimResults = true;
    recognition.continuous = true;

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let transcript = "";
      for (let i = 0; i < event.results.length; i++) {
        transcript += event.results[i][0].transcript;
      }
      onResultRef.current(transcript);
    };

    recognition.onend = () => {
      if (restartingRef.current) return;
      setListening(false);
      recognitionRef.current = null;
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error === "aborted") return;
      if (event.error === "no-speech") return;
      console.warn("SpeechRecognition error:", event.error);
      if (!restartingRef.current) {
        setListening(false);
        recognitionRef.current = null;
      }
    };

    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  }, [supported]);

  const start = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      recognitionRef.current = null;
    }
    startFresh();
  }, [startFresh]);

  const restart = useCallback(() => {
    if (!supported || !recognitionRef.current) return;
    restartingRef.current = true;
    recognitionRef.current.onend = () => {
      restartingRef.current = false;
      recognitionRef.current = null;
      startFresh();
    };
    recognitionRef.current.stop();
  }, [supported, startFresh]);

  const toggle = useCallback(() => {
    if (listening) {
      stop();
    } else {
      start();
    }
  }, [listening, start, stop]);

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
    };
  }, []);

  return { listening, supported, toggle, start, stop, restart };
}
