import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Options = {
  startOnLoad?: boolean;
  onSpeechStart: () => void;
  onSpeechEnd: (audio: Float32Array) => void;
  onVADMisfire: () => void;
};

class FakeMicVAD {
  static created: FakeMicVAD[] = [];
  static failNext: Error | null = null;
  /** 非 null 時 new() 會卡住，直到測試呼叫 release()——模擬模型還在載。 */
  static release: (() => void) | null = null;
  static waiting = false;
  start = vi.fn(async () => {});
  pause = vi.fn(async () => {});
  destroy = vi.fn(async () => {});
  constructor(public options: Options) {}
  static async new(options: Options) {
    if (FakeMicVAD.failNext) {
      const error = FakeMicVAD.failNext;
      FakeMicVAD.failNext = null;
      throw error;
    }
    if (FakeMicVAD.release) {
      FakeMicVAD.waiting = true;
      await new Promise<void>((resolve) => { FakeMicVAD.release = resolve; });
      FakeMicVAD.waiting = false;
    }
    const instance = new FakeMicVAD(options);
    FakeMicVAD.created.push(instance);
    return instance;
  }
}

vi.mock("@ricky0123/vad-web", () => ({ MicVAD: FakeMicVAD }));

import { useVad } from "./useVad";

function mount() {
  const onSpeechCommit = vi.fn();
  const onSpeechStart = vi.fn();
  const onAudio = vi.fn();
  const view = renderHook(
    ({ enabled }) => useVad({ enabled, onSpeechCommit, onSpeechStart, onAudio }),
    { initialProps: { enabled: false } },
  );
  return { ...view, onSpeechCommit, onSpeechStart, onAudio };
}

describe("useVad", () => {
  beforeEach(() => {
    FakeMicVAD.created = [];
    FakeMicVAD.failNext = null;
    FakeMicVAD.release = null;
    FakeMicVAD.waiting = false;
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("builds the instance once and reuses it across on/off cycles", async () => {
    // 每次都 destroy 再 new 的話，第一次一兩秒、之後幾百毫秒，開頭的字都漏掉。
    const { result, rerender } = mount();

    rerender({ enabled: true });
    await waitFor(() => expect(FakeMicVAD.created).toHaveLength(1));
    const instance = FakeMicVAD.created[0];
    await waitFor(() => expect(instance.start).toHaveBeenCalledTimes(1));
    expect(instance.options.startOnLoad).toBe(false);

    rerender({ enabled: false });
    await waitFor(() => expect(instance.pause).toHaveBeenCalledTimes(1));
    expect(instance.destroy).not.toHaveBeenCalled();

    rerender({ enabled: true });
    await waitFor(() => expect(instance.start).toHaveBeenCalledTimes(2));
    expect(FakeMicVAD.created).toHaveLength(1);
    expect(result.current.supported).toBe(true);
  });

  it("reports starting until the microphone is actually live", async () => {
    FakeMicVAD.release = () => {};
    const { result, rerender } = mount();

    rerender({ enabled: true });
    await waitFor(() => expect(result.current.starting).toBe(true));
    await waitFor(() => expect(FakeMicVAD.waiting).toBe(true));

    await act(async () => { FakeMicVAD.release?.(); });
    await waitFor(() => expect(result.current.starting).toBe(false));
    expect(FakeMicVAD.created[0].start).toHaveBeenCalled();
  });

  it("turning off while the model is still loading never opens the microphone", async () => {
    FakeMicVAD.release = () => {};
    const { rerender } = mount();

    rerender({ enabled: true });
    // 等 import 跑到 MicVAD.new 卡住，再關掉、再放行。
    await waitFor(() => expect(FakeMicVAD.waiting).toBe(true));
    rerender({ enabled: false });
    await act(async () => { FakeMicVAD.release?.(); });

    await waitFor(() => expect(FakeMicVAD.created).toHaveLength(1));
    expect(FakeMicVAD.created[0].start).not.toHaveBeenCalled();
  });

  it("routes speech events from the shared instance to the current cycle", async () => {
    const { result, rerender, onSpeechStart, onAudio, onSpeechCommit } = mount();
    rerender({ enabled: true });
    await waitFor(() => expect(FakeMicVAD.created).toHaveLength(1));
    const { options } = FakeMicVAD.created[0];

    act(() => { options.onSpeechStart(); });
    expect(result.current.speaking).toBe(true);
    expect(onSpeechStart).toHaveBeenCalled();

    const audio = new Float32Array([0.1]);
    act(() => { options.onSpeechEnd(audio); });
    expect(result.current.speaking).toBe(false);
    expect(onAudio).toHaveBeenCalledWith(audio);
    await waitFor(() => expect(onSpeechCommit).toHaveBeenCalled(), { timeout: 2000 });
  });

  it("events after turning off are ignored even though the instance survives", async () => {
    const { rerender, onAudio } = mount();
    rerender({ enabled: true });
    await waitFor(() => expect(FakeMicVAD.created).toHaveLength(1));
    rerender({ enabled: false });

    act(() => { FakeMicVAD.created[0].options.onSpeechEnd(new Float32Array([0.1])); });
    expect(onAudio).not.toHaveBeenCalled();
  });

  it("a failed load marks VAD unsupported so callers can fall back", async () => {
    FakeMicVAD.failNext = new Error("wasm fetch failed");
    const { result, rerender } = mount();

    rerender({ enabled: true });
    await waitFor(() => expect(result.current.supported).toBe(false));
    expect(result.current.starting).toBe(false);
  });

  it("destroys the instance only on unmount", async () => {
    const { rerender, unmount } = mount();
    rerender({ enabled: true });
    await waitFor(() => expect(FakeMicVAD.created).toHaveLength(1));

    unmount();
    await waitFor(() => expect(FakeMicVAD.created[0].destroy).toHaveBeenCalled());
  });

  it("recovers and starts listening properly under React StrictMode (mount -> unmount -> remount)", async () => {
    const onSpeechCommit = vi.fn();
    const { unmount } = renderHook(
      () => useVad({ enabled: true, onSpeechCommit }),
    );
    await waitFor(() => expect(FakeMicVAD.created.length).toBeGreaterThanOrEqual(1));
    const firstInstance = FakeMicVAD.created[0];

    unmount();
    await waitFor(() => expect(firstInstance.destroy).toHaveBeenCalled());

    const secondHook = renderHook(
      () => useVad({ enabled: true, onSpeechCommit }),
    );
    await waitFor(() => expect(FakeMicVAD.created.length).toBeGreaterThanOrEqual(2));
    const secondInstance = FakeMicVAD.created[1];
    await waitFor(() => expect(secondInstance.start).toHaveBeenCalled());
    expect(secondHook.result.current.supported).toBe(true);
  });
});
