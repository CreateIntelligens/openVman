import { useCallback, useEffect, useRef, useState } from "react";
import { fetchTtsProviders, openSpeechStream, synthesizeSpeech, type TtsProvider } from "../api";
import { isPcmStreamContentType, playPcmStream } from "../utils/ttsStream";
import { useMascot } from "../context/MascotContext";
import { resolveMascotOption } from "../data/mascotCatalog";
import { audioBufferToMascotPcm, blobToPcm16Chunks, rmsVolume } from "../utils/liveAudioUtils";
import { readScoped, writeScoped } from "../utils/scopedStorage";

type WebAudioWindow = Window & typeof globalThis & {
       webkitAudioContext?: typeof AudioContext;
};

type MascotAudioGraph = {
       analyser: AnalyserNode;
       source?: MediaElementAudioSourceNode;
};

function createAudioContext(): AudioContext | null {
       const AudioContextConstructor =
              window.AudioContext || (window as WebAudioWindow).webkitAudioContext;
       return AudioContextConstructor ? new AudioContextConstructor() : null;
}

// 影片型小助理的 WASM runtime 吃 16kHz mono int16；4096 samples 一包與 Avatar SDK 一致。
const MASCOT_PCM_SAMPLE_RATE = 16000;
const MASCOT_PCM_CHUNK_BYTES = 4096 * 2;

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
       const [ttsProvider, setTtsProvider] = useState(() => readScoped(TTS_PROVIDER_STORAGE_KEY) || "auto");
       const [ttsVoice, setTtsVoice] = useState(() => readScoped(TTS_VOICE_STORAGE_KEY) || "");
       const [ttsFallbackToast, setTtsFallbackToast] = useState("");
       const [ttsPrefetching, setTtsPrefetching] = useState(false);
       const [playingIndex, setPlayingIndex] = useState<number | null>(null);

       const audioRef = useRef<HTMLAudioElement | null>(null);
       const ttsAbortRef = useRef<AbortController | null>(null);
       const streamStopRef = useRef<(() => void) | null>(null);
       const ttsCacheRef = useRef<Map<string, CachedSpeech>>(new Map());
       const ttsPrefetchAbortRef = useRef<AbortController | null>(null);
       const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
       const mascotAudioCtxRef = useRef<AudioContext | null>(null);
       const mascotAudioGraphRef = useRef<MascotAudioGraph | null>(null);
       const mascotRafRef = useRef<number | null>(null);
       const {
              driveMouth,
              pushPcm,
              stopMouth,
              mascotOptions,
              selectedMascotId,
              registerSpeechStopper,
       } = useMascot();
       const mascotEngine = resolveMascotOption(selectedMascotId, mascotOptions).engine;
       const mascotEngineRef = useRef(mascotEngine);
       mascotEngineRef.current = mascotEngine;

       const ttsProviderRef = useRef(ttsProvider);
       ttsProviderRef.current = ttsProvider;
       const ttsVoiceRef = useRef(ttsVoice);
       ttsVoiceRef.current = ttsVoice;

       const activeTtsProvider = ttsProviders.find((provider) => provider.id === ttsProvider);

       useEffect(() => {
              fetchTtsProviders()
                     .then((providers) => {
                            setTtsProviders(providers);
                            const stored = readScoped(TTS_PROVIDER_STORAGE_KEY) || "auto";
                            if (!providers.some((p) => p.id === stored)) {
                                   setTtsProvider("auto");
                                   writeScoped(TTS_PROVIDER_STORAGE_KEY, "auto");
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
              mascotAudioGraphRef.current?.source?.disconnect();
              mascotAudioGraphRef.current?.analyser.disconnect();
              mascotAudioGraphRef.current = null;
              stopMouth();
       }, [stopMouth]);

       const stopAudio = useCallback(() => {
              ttsAbortRef.current?.abort();
              streamStopRef.current?.();
              streamStopRef.current = null;
              if (audioRef.current) {
                     audioRef.current.pause();
                     audioRef.current = null;
              }
              stopMascotAnalyser();
              setPlayingIndex(null);
       }, [stopMascotAnalyser]);

       useEffect(() => {
              return registerSpeechStopper(() => {
                     stopAudio();
              });
       }, [registerSpeechStopper, stopAudio]);

       const ensureMascotContext = useCallback((): AudioContext | null => {
              if (!mascotAudioCtxRef.current) {
                     mascotAudioCtxRef.current = createAudioContext();
              }
              return mascotAudioCtxRef.current;
       }, []);

       // 建一個接到喇叭的 analyser，並開 rAF 迴圈把音量送給小助理；回傳 analyser 讓來源接上。
       const startMascotAnalyser = useCallback((ctx: AudioContext): AnalyserNode => {
              const analyser = ctx.createAnalyser();
              analyser.fftSize = 256;
              analyser.connect(ctx.destination);
              mascotAudioGraphRef.current = { analyser };
              const data = new Uint8Array(analyser.fftSize);
              const loop = () => {
                     analyser.getByteTimeDomainData(data);
                     driveMouth(rmsVolume(data));
                     mascotRafRef.current = requestAnimationFrame(loop);
              };
              mascotRafRef.current = requestAnimationFrame(loop);
              return analyser;
       }, [driveMouth]);

       const driveMascotFromAudio = useCallback((audio: HTMLAudioElement) => {
              stopMascotAnalyser();
              const ctx = ensureMascotContext();
              if (!ctx) return;
              try {
                     const source = ctx.createMediaElementSource(audio);
                     const analyser = startMascotAnalyser(ctx);
                     source.connect(analyser);
                     mascotAudioGraphRef.current = { analyser, source };
              } catch (reason) {
                     console.warn("Failed to connect mascot audio analyser:", reason);
                     stopMascotAnalyser();
              }
       }, [ensureMascotContext, startMascotAnalyser, stopMascotAnalyser]);

       // 邊收邊播：串流一到就排進 AudioContext，小助理同步拿音量與 PCM。
       // 回傳 false 表示這個回應不能串流（例如 mp3），交給整段路徑。
       const playStreamedSpeech = useCallback(async (response: Response, cacheKey: string, fallback?: string): Promise<boolean> => {
              const contentType = response.headers.get("Content-Type") ?? "";
              if (!response.ok || !response.body || !isPcmStreamContentType(contentType)) {
                     return false;
              }
              const ctx = ensureMascotContext();
              if (!ctx) return false;
              if (ctx.state === "suspended") {
                     await ctx.resume();
              }
              if (fallback) {
                     setTtsFallbackToast(fallback);
                     if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
                     toastTimerRef.current = setTimeout(() => setTtsFallbackToast(""), 5000);
              }
              stopMascotAnalyser();
              const analyser = startMascotAnalyser(ctx);
              const wantsPcm = mascotEngineRef.current === "video";
              const playback = playPcmStream(response, ctx, {
                     outputNode: analyser,
                     onChunk: (buffer) => {
                            if (!wantsPcm) return;
                            for (const chunk of audioBufferToMascotPcm(buffer, MASCOT_PCM_SAMPLE_RATE, MASCOT_PCM_CHUNK_BYTES)) {
                                   pushPcm(chunk);
                            }
                     },
              });
              streamStopRef.current = playback.stop;
              try {
                     const wav = await playback.done;
                     setTtsCacheEntry(ttsCacheRef.current, cacheKey, { audio: wav, fallback });
              } finally {
                     if (streamStopRef.current === playback.stop) {
                            streamStopRef.current = null;
                            stopMascotAnalyser();
                            setPlayingIndex(null);
                     }
              }
              return true;
       }, [ensureMascotContext, pushPcm, startMascotAnalyser, stopMascotAnalyser]);

       // 只有影片型小助理需要 PCM；解碼在 play() 之前完成，讓嘴型與聲音同時起跑。
       const decodeMascotPcm = useCallback(async (buffer: ArrayBuffer): Promise<ArrayBuffer[]> => {
              if (mascotEngineRef.current !== "video") {
                     return [];
              }
              if (!mascotAudioCtxRef.current) {
                     const ctx = createAudioContext();
                     if (!ctx) {
                            return [];
                     }
                     mascotAudioCtxRef.current = ctx;
              }
              try {
                     return await blobToPcm16Chunks(
                            new Blob([buffer]),
                            mascotAudioCtxRef.current,
                            MASCOT_PCM_SAMPLE_RATE,
                            MASCOT_PCM_CHUNK_BYTES,
                     );
              } catch (reason) {
                     console.warn("Failed to decode TTS audio for mascot lip sync:", reason);
                     return [];
              }
       }, []);

       const playAudioBuffer = useCallback(async (buffer: ArrayBuffer, fallback?: string) => {
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
              const pcmChunks = await decodeMascotPcm(buffer);
              if (audioRef.current !== audio) {
                     // 解碼期間被 stopAudio 取消
                     URL.revokeObjectURL(url);
                     return;
              }
              audio.play()
                     .then(() => {
                            driveMascotFromAudio(audio);
                            for (const chunk of pcmChunks) pushPcm(chunk);
                     })
                     .catch(cleanup);
       }, [decodeMascotPcm, driveMascotFromAudio, pushPcm, stopMascotAnalyser]);

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
                     await playAudioBuffer(cached.audio, cached.fallback);
                     return;
              }

              const controller = new AbortController();
              ttsAbortRef.current = controller;
              try {
                     // 先試串流端點：auto 或支援串流的 provider 會邊生成邊回 PCM；
                     // 回的不是 PCM（例如 mp3）就退回整段路徑。
                     if (!selection.provider || selection.provider === "voxcpm" || selection.provider === "gemini-tts" || selection.provider === "indextts") {
                            const response = await openSpeechStream(text, { ...selection, signal: controller.signal });
                            const streamed = await playStreamedSpeech(
                                   response,
                                   key,
                                   response.headers.get("X-TTS-Fallback-Reason") || undefined,
                            );
                            if (streamed) return;
                     }
                     const { audio, fallback } = await synthesizeSpeech(text, {
                            ...selection,
                            signal: controller.signal,
                     });
                     setTtsCacheEntry(ttsCacheRef.current, key, { audio, fallback });
                     await playAudioBuffer(audio, fallback);
              } catch (reason) {
                     if (!controller.signal.aborted) {
                            console.error("TTS playback failed:", reason);
                     }
                     setPlayingIndex(null);
              }
       }, [playAudioBuffer, playStreamedSpeech, playingIndex, stopAudio]);

       const handleTtsProviderChange = useCallback((id: string) => {
              setTtsProvider(id);
              writeScoped(TTS_PROVIDER_STORAGE_KEY, id);
              const provider = ttsProviders.find((item) => item.id === id);
              const nextVoice = provider?.default_voice || "";
              setTtsVoice(nextVoice);
              writeScoped(TTS_VOICE_STORAGE_KEY, nextVoice);
       }, [ttsProviders]);

       const handleTtsVoiceChange = useCallback((voice: string) => {
              setTtsVoice(voice);
              writeScoped(TTS_VOICE_STORAGE_KEY, voice);
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
