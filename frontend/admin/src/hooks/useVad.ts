import { useCallback, useEffect, useRef, useState } from "react";
import { VadRecognizer } from "@shared/speech";

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
 * useVad — 薄層轉接：將 React 狀態綁定到底層無框架的 VadRecognizer。
 *
 * 實例跨次開關重用：只做一次模型與 worklet 載入，之後每次開關只剩 pause()/start()。
 * starting 是「按下去到真的開始收音」那段，畫面照實顯示。
 * 供後台聊天室與 Live 模式使用。
 */
export function useVad({ onSpeechCommit, onSpeechStart, onAudio, enabled }: UseVadOptions) {
  const [speaking, setSpeaking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [supported, setSupported] = useState(true);

  const recognizerRef = useRef<VadRecognizer | null>(null);
  const onSpeechCommitRef = useRef(onSpeechCommit);
  onSpeechCommitRef.current = onSpeechCommit;
  const onSpeechStartRef = useRef(onSpeechStart);
  onSpeechStartRef.current = onSpeechStart;
  const onAudioRef = useRef(onAudio);
  onAudioRef.current = onAudio;

  const getOrCreateRecognizer = useCallback(() => {
    if (!recognizerRef.current || !recognizerRef.current.isAlive) {
      recognizerRef.current = new VadRecognizer({
        commitMode: "continuous",
        silenceTimeoutMs: 1000,
        onSpeechStart: () => onSpeechStartRef.current?.(),
        onSpeechEnd: (audio) => onAudioRef.current?.(audio),
        onSpeechCommit: () => onSpeechCommitRef.current(),
        onSpeakingChange: (val) => setSpeaking(val),
        onStartingChange: (val) => setStarting(val),
        onError: (code) => {
          if (code === "vad-unavailable") {
            setSupported(false);
          }
        },
      });
    }
    return recognizerRef.current;
  }, []);

  getOrCreateRecognizer();

  useEffect(() => {
    let cancelled = false;
    const recognizer = getOrCreateRecognizer();

    if (enabled) {
      void recognizer.start().then(() => {
        if (!cancelled) {
          setSupported(recognizer.supported);
        }
      });
    } else {
      recognizer.stop();
    }

    return () => {
      cancelled = true;
      recognizer.stop();
    };
  }, [enabled, getOrCreateRecognizer]);

  useEffect(() => {
    return () => {
      recognizerRef.current?.dispose();
      recognizerRef.current = null;
    };
  }, []);

  return { speaking, starting, supported };
}
