import { useCallback, useEffect, useRef, useState } from "react";
import { fetchTtsProviders, synthesizeSpeech, type TtsProvider } from "../api";
import { useMascot } from "../context/MascotContext";

type WebAudioWindow = Window & typeof globalThis & {
       webkitAudioContext?: typeof AudioContext;
};

type MascotAudioGraph = {
       analyser: AnalyserNode;
       source: MediaElementAudioSourceNode;
};

function createAudioContext(): AudioContext | null {
       const AudioContextConstructor =
              window.AudioContext || (window as WebAudioWindow).webkitAudioContext;
       return AudioContextConstructor ? new AudioContextConstructor() : null;
}

function rmsVolume(data: Uint8Array): number {
       let sum = 0;
       for (let i = 0; i < data.length; i++) {
              const v = (data[i] - 128) / 128;
              sum += v * v;
       }
       return Math.min(1, Math.sqrt(sum / data.length) * 3.4);
}

const TTS_PROVIDER_STORAGE_KEY = "brain-tts-provider";
const TTS_VOICE_STORAGE_KEY = "brain-tts-voice";
const TTS_CACHE_MAX = 50;

type CachedSpeech = {
       audio: ArrayBuffer;
       fallback?: string;
};

type TtsSelection = {
       provider: string;
       voice: string;
};

function resolveTtsSelection(provider: string, voice: string): TtsSelection {
       if (provider === "auto") {
              return { provider: "", voice: "" };
       }
       return { provider, voice };
}

async function ttsCacheKey(text: string, provider: string, voice: string): Promise<string> {
       const raw = `${text}|${provider}|${voice}`;
       const cryptoObj = globalThis.crypto;
       if (!cryptoObj?.subtle) {
              return raw;
       }
       const buf = await cryptoObj.subtle.digest("SHA-256", new TextEncoder().encode(raw));
       return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function setTtsCacheEntry(cache: Map<string, CachedSpeech>, key: string, value: CachedSpeech): void {
       if (cache.has(key)) {
              cache.delete(key);
       } else if (cache.size >= TTS_CACHE_MAX) {
              const oldest = cache.keys().next().value;
              if (oldest !== undefined) {
                     cache.delete(oldest);
              }
       }
       cache.set(key, value);
}

export function useTts() {
       const [ttsProviders, setTtsProviders] = useState<TtsProvider[]>([]);
       const [ttsProvider, setTtsProvider] = useState(() => localStorage.getItem(TTS_PROVIDER_STORAGE_KEY) || "auto");
       const [ttsVoice, setTtsVoice] = useState(() => localStorage.getItem(TTS_VOICE_STORAGE_KEY) || "");
       const [ttsFallbackToast, setTtsFallbackToast] = useState("");
       const [ttsPrefetching, setTtsPrefetching] = useState(false);
       const [playingIndex, setPlayingIndex] = useState<number | null>(null);

       const audioRef = useRef<HTMLAudioElement | null>(null);
       const ttsAbortRef = useRef<AbortController | null>(null);
       const ttsCacheRef = useRef<Map<string, CachedSpeech>>(new Map());
       const ttsPrefetchAbortRef = useRef<AbortController | null>(null);
       const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
       const mascotAudioCtxRef = useRef<AudioContext | null>(null);
       const mascotAudioGraphRef = useRef<MascotAudioGraph | null>(null);
       const mascotRafRef = useRef<number | null>(null);
       const { driveMouth, stopMouth } = useMascot();

       const ttsProviderRef = useRef(ttsProvider);
       ttsProviderRef.current = ttsProvider;
       const ttsVoiceRef = useRef(ttsVoice);
       ttsVoiceRef.current = ttsVoice;

       const activeTtsProvider = ttsProviders.find((provider) => provider.id === ttsProvider);

       useEffect(() => {
              fetchTtsProviders()
                     .then((providers) => {
                            setTtsProviders(providers);
                            const stored = localStorage.getItem(TTS_PROVIDER_STORAGE_KEY) || "auto";
                            if (!providers.some((p) => p.id === stored)) {
                                   setTtsProvider("auto");
                                   localStorage.setItem(TTS_PROVIDER_STORAGE_KEY, "auto");
                            }
                     })
                     .catch((reason) => console.warn("Failed to load TTS providers:", reason));
       }, []);

       const clearTtsPrefetchState = useCallback(() => {
              ttsPrefetchAbortRef.current?.abort();
              ttsCacheRef.current.clear();
       }, []);

       const stopMascotAnalyser = useCallback(() => {
              if (mascotRafRef.current !== null) {
                     cancelAnimationFrame(mascotRafRef.current);
                     mascotRafRef.current = null;
              }
              mascotAudioGraphRef.current?.source.disconnect();
              mascotAudioGraphRef.current?.analyser.disconnect();
              mascotAudioGraphRef.current = null;
              stopMouth();
       }, [stopMouth]);

       const stopAudio = useCallback(() => {
              ttsAbortRef.current?.abort();
              if (audioRef.current) {
                     audioRef.current.pause();
                     audioRef.current = null;
              }
              stopMascotAnalyser();
              setPlayingIndex(null);
       }, [stopMascotAnalyser]);

       const driveMascotFromAudio = useCallback((audio: HTMLAudioElement) => {
              stopMascotAnalyser();
              if (!mascotAudioCtxRef.current) {
                     const ctx = createAudioContext();
                     if (!ctx) {
                            return;
                     }
                     mascotAudioCtxRef.current = ctx;
              }

              try {
                     const ctx = mascotAudioCtxRef.current;
                     const source = ctx.createMediaElementSource(audio);
                     const analyser = ctx.createAnalyser();
                     analyser.fftSize = 256;
                     source.connect(analyser);
                     analyser.connect(ctx.destination);
                     mascotAudioGraphRef.current = { analyser, source };
                     const data = new Uint8Array(analyser.fftSize);

                     const loop = () => {
                            analyser.getByteTimeDomainData(data);
                            driveMouth(rmsVolume(data));
                            mascotRafRef.current = requestAnimationFrame(loop);
                     };
                     mascotRafRef.current = requestAnimationFrame(loop);
              } catch (reason) {
                     console.warn("Failed to connect mascot audio analyser:", reason);
                     stopMascotAnalyser();
              }
       }, [driveMouth, stopMascotAnalyser]);

       const playAudioBuffer = useCallback((buffer: ArrayBuffer, fallback?: string) => {
              if (fallback) {
                     setTtsFallbackToast(fallback);
                     if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
                     toastTimerRef.current = setTimeout(() => setTtsFallbackToast(""), 5000);
              }

              const blob = new Blob([buffer], { type: "audio/wav" });
              const url = URL.createObjectURL(blob);
              const audio = new Audio(url);
              audioRef.current = audio;

              const cleanup = () => {
                     setPlayingIndex(null);
                     audioRef.current = null;
                     URL.revokeObjectURL(url);
                     stopMascotAnalyser();
              };

              audio.onended = cleanup;
              audio.play()
                     .then(() => driveMascotFromAudio(audio))
                     .catch(cleanup);
       }, [driveMascotFromAudio, stopMascotAnalyser]);

       const prefetchTts = useCallback(async (text: string) => {
              ttsPrefetchAbortRef.current?.abort();
              const selection = resolveTtsSelection(ttsProviderRef.current, ttsVoiceRef.current);
              const key = await ttsCacheKey(text, selection.provider, selection.voice);
              if (ttsCacheRef.current.has(key)) {
                     return;
              }

              const controller = new AbortController();
              ttsPrefetchAbortRef.current = controller;
              setTtsPrefetching(true);
              try {
                     const { audio, fallback } = await synthesizeSpeech(text, {
                            ...selection,
                            signal: controller.signal,
                     });
                     setTtsCacheEntry(ttsCacheRef.current, key, { audio, fallback });
              } catch (reason) {
                     if (!controller.signal.aborted) {
                            console.warn("TTS prefetch failed:", reason);
                     }
              } finally {
                     ttsPrefetchAbortRef.current = null;
                     setTtsPrefetching(false);
              }
       }, []);

       const playTts = useCallback(async (text: string, index: number) => {
              const shouldStopCurrent = playingIndex === index;
              stopAudio();
              if (shouldStopCurrent) {
                     return;
              }

              setPlayingIndex(index);

              const selection = resolveTtsSelection(ttsProviderRef.current, ttsVoiceRef.current);
              const key = await ttsCacheKey(text, selection.provider, selection.voice);
              const cached = ttsCacheRef.current.get(key);
              if (cached) {
                     setTtsCacheEntry(ttsCacheRef.current, key, cached);
                     playAudioBuffer(cached.audio, cached.fallback);
                     return;
              }

              const controller = new AbortController();
              ttsAbortRef.current = controller;
              try {
                     const { audio, fallback } = await synthesizeSpeech(text, {
                            ...selection,
                            signal: controller.signal,
                     });
                     setTtsCacheEntry(ttsCacheRef.current, key, { audio, fallback });
                     playAudioBuffer(audio, fallback);
              } catch (reason) {
                     if (!controller.signal.aborted) {
                            console.error("TTS playback failed:", reason);
                     }
                     setPlayingIndex(null);
              }
       }, [playAudioBuffer, playingIndex, stopAudio]);

       const handleTtsProviderChange = useCallback((id: string) => {
              setTtsProvider(id);
              localStorage.setItem(TTS_PROVIDER_STORAGE_KEY, id);
              const provider = ttsProviders.find((item) => item.id === id);
              const nextVoice = provider?.default_voice || "";
              setTtsVoice(nextVoice);
              localStorage.setItem(TTS_VOICE_STORAGE_KEY, nextVoice);
       }, [ttsProviders]);

       const handleTtsVoiceChange = useCallback((voice: string) => {
              setTtsVoice(voice);
              localStorage.setItem(TTS_VOICE_STORAGE_KEY, voice);
       }, []);

       useEffect(() => () => {
              ttsAbortRef.current?.abort();
              ttsPrefetchAbortRef.current?.abort();
              audioRef.current?.pause();
              if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
              stopMascotAnalyser();
              void mascotAudioCtxRef.current?.close();
              mascotAudioCtxRef.current = null;
       }, [stopMascotAnalyser]);

       return {
              ttsProviders,
              ttsProvider,
              ttsVoice,
              ttsFallbackToast,
              ttsPrefetching,
              playingIndex,
              activeTtsProvider,
              setTtsFallbackToast,
              clearTtsPrefetchState,
              stopAudio,
              prefetchTts,
              playTts,
              handleTtsProviderChange,
              handleTtsVoiceChange,
       };
}
