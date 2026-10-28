import { afterEach, describe, expect, it, vi } from "vitest";

import { openSpeechStream, synthesizeSpeech, synthesizeSpeechPreview } from "./tts";

afterEach(() => vi.unstubAllGlobals());

describe("speech preview API", () => {
  it.each(["audio/wav", "audio/mpeg"])("keeps the actual %s format and authenticated request", async (type) => {
    const fetch = vi.fn().mockResolvedValue(new Response("audio", {
      headers: { "Content-Type": type, "X-TTS-Provider": "edge" },
    }));
    vi.stubGlobal("fetch", fetch);
    const signal = new AbortController().signal;
    const result = await synthesizeSpeechPreview("你好", "edge", "voice-a", signal);
    expect(result.audio.type).toBe(type);
    expect(result.provider).toBe("edge");
    expect(result.fallback).toBe(false);
    expect(fetch).toHaveBeenCalledWith("/v1/audio/speech", expect.objectContaining({
      credentials: "include", signal,
      body: JSON.stringify({ input: "你好", provider: "edge", voice: "voice-a" }),
    }));
  });

  it("forwards the turn's speech language on chat playback paths", async () => {
    const fetch = vi.fn().mockImplementation(async () => new Response("audio", {
      headers: { "Content-Type": "audio/mpeg" },
    }));
    vi.stubGlobal("fetch", fetch);
    await openSpeechStream("你好", { provider: "voxcpm", speechLanguage: "nan" });
    await synthesizeSpeech("你好", { provider: "edge", speechLanguage: "nan" });
    await synthesizeSpeech("你好", { provider: "edge" });
    const bodies = fetch.mock.calls.map(([, init]) => JSON.parse(init.body));
    expect(bodies[0]).toEqual({ text: "你好", provider: "voxcpm", speech_language: "nan" });
    expect(bodies[1]).toEqual({ input: "你好", provider: "edge", speech_language: "nan" });
    expect(bodies[2]).toEqual({ input: "你好", provider: "edge" });
  });

  it("identifies fallback on cached results without a fallback header", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("audio", {
      headers: { "Content-Type": "audio/mpeg", "X-TTS-Provider": "edge" },
    })));
    const result = await synthesizeSpeechPreview("你好", "gemini", "Kore", new AbortController().signal);
    expect(result.fallback).toBe(true);
  });

  it.each([
    new Response("", { headers: { "Content-Type": "audio/wav" } }),
    new Response("{}", { headers: { "Content-Type": "application/json" } }),
    new Response("unavailable", { status: 502 }),
  ])("rejects empty, invalid, or failed audio responses", async (response) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(synthesizeSpeechPreview("你好", "edge", "voice-a", new AbortController().signal)).rejects.toThrow();
  });
});
