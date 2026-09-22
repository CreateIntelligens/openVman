import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const transcribeOnServerMock = vi.fn();
vi.mock("../api/asr", () => ({
  transcribeOnServer: (clip: Blob, filename: string) => transcribeOnServerMock(clip, filename),
}));

type VadOptions = { enabled: boolean; onAudio?: (audio: Float32Array) => void; onSpeechStart?: () => void };
let vadOptions: VadOptions;
vi.mock("./useVad", () => ({
  useVad: (options: VadOptions) => {
    vadOptions = options;
    return { speaking: false, starting: false, supported: true };
  },
}));

import { useVadSpeechRecognition } from "./useVadSpeechRecognition";

function mount() {
  const onActivity = vi.fn();
  const onError = vi.fn();
  const onFinalTranscript = vi.fn();
  const view = renderHook(() => useVadSpeechRecognition({
    enabled: true, onActivity, onError, onFinalTranscript,
  }));
  return { ...view, onActivity, onError, onFinalTranscript };
}

describe("useVadSpeechRecognition", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    transcribeOnServerMock.mockResolvedValue({ text: " 你好 ", provider: "breeze" });
  });

  it("VAD 切出一句就包成 WAV 上傳，不必使用者再按一次", async () => {
    const { onFinalTranscript } = mount();

    act(() => { vadOptions.onAudio?.(new Float32Array([0, 0.5, -0.5])); });

    await waitFor(() => expect(onFinalTranscript).toHaveBeenCalledWith("你好"));
    const [clip, filename] = transcribeOnServerMock.mock.calls[0];
    expect(filename).toBe("speech.wav");
    expect((clip as Blob).type).toBe("audio/wav");
    // 44 bytes 標頭 + 3 個 16-bit 取樣。
    expect((clip as Blob).size).toBe(44 + 6);
  });

  it("講話開始時回報活動，讓閒置計時重置", () => {
    const { onActivity } = mount();
    act(() => { vadOptions.onSpeechStart?.(); });
    expect(onActivity).toHaveBeenCalled();
  });

  it("切到辨識不出東西的雜音時安靜略過，不跳錯誤", async () => {
    transcribeOnServerMock.mockResolvedValue({ text: "（音訊轉錄失敗）", provider: "breeze" });
    const { result, onError, onFinalTranscript } = mount();

    act(() => { vadOptions.onAudio?.(new Float32Array([0.1])); });

    await waitFor(() => expect(result.current.transcribing).toBe(false));
    expect(onFinalTranscript).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });

  it("好幾句同時在等後端時，先回來的那句不會提早關掉辨識中", async () => {
    const releases: Array<(v: { text: string; provider: string }) => void> = [];
    transcribeOnServerMock.mockImplementation(
      () => new Promise((resolve) => { releases.push(resolve); }),
    );
    const { result } = mount();

    act(() => {
      vadOptions.onAudio?.(new Float32Array([0.1]));
      vadOptions.onAudio?.(new Float32Array([0.2]));
    });
    await waitFor(() => expect(result.current.transcribing).toBe(true));

    await act(async () => { releases[0]({ text: "一", provider: "breeze" }); });
    expect(result.current.transcribing).toBe(true);
    await act(async () => { releases[1]({ text: "二", provider: "breeze" }); });
    expect(result.current.transcribing).toBe(false);
  });
});
