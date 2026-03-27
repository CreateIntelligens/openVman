import { parseErrorMessage } from "./common";

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
  const res = await fetch("/v1/tts/providers");
  if (!res.ok) {
    const msg = await parseErrorMessage(res);
    throw new Error(msg);
  }
  return res.json();
}

export async function synthesizeSpeech(
  text: string,
  opts?: { provider?: string; voice?: string; signal?: AbortSignal },
): Promise<SpeechResult> {
  const body: Record<string, string> = { input: text };
  if (opts?.provider) body.provider = opts.provider;
  if (opts?.voice) body.voice = opts.voice;

  const res = await fetch("/v1/audio/speech", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: opts?.signal,
  });
  if (!res.ok) {
    const msg = await parseErrorMessage(res);
    throw new Error(msg);
  }
  const audio = await res.arrayBuffer();
  const fallbackReason = res.headers.get("X-TTS-Fallback-Reason") || undefined;
  return { audio, fallback: fallbackReason };
}
