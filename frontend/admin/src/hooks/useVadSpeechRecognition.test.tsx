import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
vi.mock("../api/common", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  parseErrorMessage: vi.fn(),
}));

class FakeMicVAD {
  static created: FakeMicVAD[] = [];
  start = vi.fn(async () => {});
  pause = vi.fn(async () => {});
  destroy = vi.fn(async () => {});
  constructor(public options: {
    onSpeechStart: () => void;
    onSpeechEnd: (audio: Float32Array) => void;
    onVADMisfire: () => void;
  }) {
    FakeMicVAD.created.push(this);
  }
  static async new(options: any) {
    return new FakeMicVAD(options);
  }
}

vi.mock("@ricky0123/vad-web", () => ({ MicVAD: FakeMicVAD }));

import { useVadSpeechRecognition } from "./useVadSpeechRecognition";

function mount() {
  const onActivity = vi.fn();
  const onError = vi.fn();
  const onFinalTranscript = vi.fn();
  const view = renderHook(() =>
    useVadSpeechRecognition({
      enabled: true,
      onActivity,
      onError,
      onFinalTranscript,
    }),
  );
  return { ...view, onActivity, onError, onFinalTranscript };
}

describe("useVadSpeechRecognition (admin hook)", () => {
  beforeEach(() => {
    FakeMicVAD.created = [];
    vi.clearAllMocks();
    apiFetchMock.mockResolvedValue(
      new Response(JSON.stringify({ text: " 你好 ", provider: "breeze" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("VAD 切出一句就包成 WAV 上傳，不必使用者再按一次", async () => {
    const { onFinalTranscript } = mount();
    await waitFor(() => expect(FakeMicVAD.created).toHaveLength(1));

    act(() => {
      FakeMicVAD.created[0].options.onSpeechEnd(new Float32Array([0, 0.5, -0.5]));
    });

    await waitFor(() => expect(onFinalTranscript).toHaveBeenCalledWith("你好"));
    const [path, init] = apiFetchMock.mock.calls[0];
    expect(path).toBe("/api/v1/asr/transcribe");
    const file = (init.body as FormData).get("file") as File;
    expect(file.name).toBe("speech.wav");
    // 44 bytes 標頭 + 3 個 16-bit 取樣 (6 bytes)。
    expect(file.size).toBe(44 + 6);
  });

  it("講話開始時回報活動，讓閒置計時重置", async () => {
    const { onActivity } = mount();
    await waitFor(() => expect(FakeMicVAD.created).toHaveLength(1));

    act(() => {
      FakeMicVAD.created[0].options.onSpeechStart();
    });
    expect(onActivity).toHaveBeenCalled();
  });

  it("切到辨識不出東西的雜音時安靜略過，不跳錯誤", async () => {
    apiFetchMock.mockResolvedValue(
      new Response(JSON.stringify({ text: "（音訊轉錄失敗）", provider: "breeze" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { result, onError, onFinalTranscript } = mount();
    await waitFor(() => expect(FakeMicVAD.created).toHaveLength(1));

    act(() => {
      FakeMicVAD.created[0].options.onSpeechEnd(new Float32Array([0.1]));
    });

    await waitFor(() => expect(result.current.transcribing).toBe(false));
    expect(onFinalTranscript).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });

  it("好幾句同時在等後端時，先回來的那句不會提早關掉辨識中", async () => {
    const releases: Array<(res: Response) => void> = [];
    apiFetchMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          releases.push(resolve);
        }),
    );
    const { result } = mount();
    await waitFor(() => expect(FakeMicVAD.created).toHaveLength(1));

    act(() => {
      FakeMicVAD.created[0].options.onSpeechEnd(new Float32Array([0.1]));
      FakeMicVAD.created[0].options.onSpeechEnd(new Float32Array([0.2]));
    });
    await waitFor(() => expect(result.current.transcribing).toBe(true));

    await act(async () => {
      releases[0](
        new Response(JSON.stringify({ text: "一", provider: "breeze" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    expect(result.current.transcribing).toBe(true);

    await act(async () => {
      releases[1](
        new Response(JSON.stringify({ text: "二", provider: "breeze" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    expect(result.current.transcribing).toBe(false);
  });
});
