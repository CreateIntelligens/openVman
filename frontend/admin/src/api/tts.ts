import { apiFetch, fetchJson } from "./common";

export interface TtsProvider {
  id: string;
  name: string;
  default_voice: string;
  voices: string[];
}

export interface SpeechResult {
  audio: ArrayBuffer;
  fallback?: string;
}

export async function fetchTtsProviders(): Promise<TtsProvider[]> {
  return fetchJson<TtsProvider[]>("/api/v1/tts/providers");
}

export interface SpeechPreview {
  audio: Blob;
  provider: string;
  fallback: boolean;
}

export async function synthesizeSpeechPreview(
  text: string,
  provider: string,
  voice: string,
  signal: AbortSignal,
): Promise<SpeechPreview> {
  const response = await apiFetch("/v1/audio/speech", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input: text, provider, voice }),
    signal,
  });
  if (!response.ok) {
    throw new Error(`語音產生失敗（HTTP ${response.status}），請稍後重試。`);
  }
  // 各供應商可能回傳 WAV 或 MP3，保留伺服器實際的 MIME type。
  const audio = await response.blob();
  if (!audio.size || !audio.type.startsWith("audio/")) {
    throw new Error("未收到可播放的音訊，請換一個聲音或稍後重試。");
  }
  const actualProvider = response.headers.get("X-TTS-Provider") || "";
  return {
    audio,
    provider: actualProvider,
    fallback: response.headers.get("X-TTS-Fallback") === "true"
      || Boolean(provider && actualProvider && provider !== actualProvider),
  };
}

/** 打串流端點，回傳原始 Response 讓呼叫端邊收邊播；provider 空字串表示交給後端決定。 */
export async function openSpeechStream(
  text: string,
  opts?: { provider?: string; voice?: string; signal?: AbortSignal },
): Promise<Response> {
  const body: Record<string, string> = { text };
  if (opts?.provider) body.provider = opts.provider;
  if (opts?.voice) body.voice = opts.voice;
  return apiFetch("/api/v1/tts/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: opts?.signal,
  });
}

export async function synthesizeSpeech(
  text: string,
  opts?: { provider?: string; voice?: string; signal?: AbortSignal },
): Promise<SpeechResult> {
  const provider = opts?.provider;
  if (provider === "voxcpm") {
    try {
      const streamBody: Record<string, string> = { text, provider };
      if (opts?.voice) streamBody.voice = opts.voice;

      const res = await apiFetch("/api/v1/tts/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(streamBody),
        signal: opts?.signal,
      });
      if (res.ok) {
        const audio = await res.arrayBuffer();
        const fallbackReason = res.headers.get("X-TTS-Fallback-Reason") || undefined;
        return { audio, fallback: fallbackReason };
      }
    } catch {
      // 串流端點異常時往下 fallback 至 /v1/audio/speech
    }
  }

  const body: Record<string, string> = { input: text };
  if (opts?.provider) body.provider = opts.provider;
  if (opts?.voice) body.voice = opts.voice;

  const res = await apiFetch("/v1/audio/speech", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: opts?.signal,
  });
  if (!res.ok) {
    throw new Error(`Synthesis failed: ${res.status}`);
  }
  const audio = await res.arrayBuffer();
  const fallbackReason = res.headers.get("X-TTS-Fallback-Reason") || undefined;
  return { audio, fallback: fallbackReason };
}
