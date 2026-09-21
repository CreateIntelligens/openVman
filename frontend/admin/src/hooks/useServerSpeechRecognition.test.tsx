import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const transcribeOnServerMock = vi.fn();
vi.mock("../api/asr", () => ({
  transcribeOnServer: (clip: Blob, filename: string) => transcribeOnServerMock(clip, filename),
}));

import { useServerSpeechRecognition } from "./useServerSpeechRecognition";

class FakeRecorder {
  static instances: FakeRecorder[] = [];
  static isTypeSupported = (type: string) => type === "audio/webm";
  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  /** 測試用：這一段錄到的內容；空字串代表什麼都沒錄到。 */
  payload = "audio-bytes";

  constructor(_stream: MediaStream, options: { mimeType?: string }) {
    this.mimeType = options.mimeType ?? "";
    FakeRecorder.instances.push(this);
  }
  start() { this.state = "recording"; }
  stop() {
    this.state = "inactive";
    if (this.payload) this.ondataavailable?.({ data: new Blob([this.payload]) });
    this.onstop?.();
  }
}

const stopTrack = vi.fn();

function mount(initialEnabled = false) {
  const onError = vi.fn();
  const onFinalTranscript = vi.fn();
  const view = renderHook(
    ({ enabled }) => useServerSpeechRecognition({ enabled, onError, onFinalTranscript }),
    { initialProps: { enabled: initialEnabled } },
  );
  return { ...view, onError, onFinalTranscript };
}

describe("useServerSpeechRecognition", () => {
  beforeEach(() => {
    FakeRecorder.instances = [];
    vi.clearAllMocks();
    vi.stubGlobal("MediaRecorder", FakeRecorder);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] }),
      },
    });
    transcribeOnServerMock.mockResolvedValue({ text: " 你好 ", provider: "breeze" });
  });

  afterEach(() => { vi.unstubAllGlobals(); });

  it("開始收音後回報 recording，停止才上傳並交出轉寫結果", async () => {
    const { result, rerender, onFinalTranscript } = mount();

    rerender({ enabled: true });
    await waitFor(() => expect(result.current.recording).toBe(true));
    // 還在錄的時候不該送任何東西——伺服器引擎沒有中途結果。
    expect(transcribeOnServerMock).not.toHaveBeenCalled();

    rerender({ enabled: false });

    await waitFor(() => expect(onFinalTranscript).toHaveBeenCalledWith("你好"));
    expect(result.current.recording).toBe(false);
    // 副檔名要對應實際的容器格式，後端靠它決定怎麼解。
    expect(transcribeOnServerMock.mock.calls[0][1]).toBe("speech.webm");
    // 麥克風要放掉，不然瀏覽器分頁上的錄音指示燈會一直亮著。
    expect(stopTrack).toHaveBeenCalled();
  });

  it("等後端回字的期間 transcribing 為 true", async () => {
    let release: (value: { text: string; provider: string }) => void = () => {};
    transcribeOnServerMock.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    const { result, rerender } = mount();

    rerender({ enabled: true });
    await waitFor(() => expect(result.current.recording).toBe(true));
    rerender({ enabled: false });

    await waitFor(() => expect(result.current.transcribing).toBe(true));
    await act(async () => { release({ text: "好", provider: "breeze" }); });
    expect(result.current.transcribing).toBe(false);
  });

  it("後端的失敗佔位字不會被當成使用者說的話送出", async () => {
    transcribeOnServerMock.mockResolvedValue({ text: "（音訊轉錄失敗）", provider: "breeze" });
    const { result, rerender, onError, onFinalTranscript } = mount();

    rerender({ enabled: true });
    await waitFor(() => expect(result.current.recording).toBe(true));
    rerender({ enabled: false });

    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect(onFinalTranscript).not.toHaveBeenCalled();
  });

  it("什麼都沒錄到就不上傳", async () => {
    const { result, rerender, onError } = mount();

    rerender({ enabled: true });
    await waitFor(() => expect(result.current.recording).toBe(true));
    FakeRecorder.instances[0].payload = "";
    rerender({ enabled: false });

    await waitFor(() => expect(onError).toHaveBeenCalledWith("沒有錄到聲音。"));
    expect(transcribeOnServerMock).not.toHaveBeenCalled();
  });

  it("麥克風權限被拒時回報錯誤而不是卡在收音中", async () => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValue(new Error("denied"));
    const { result, rerender, onError } = mount();

    rerender({ enabled: true });

    await waitFor(() => expect(onError).toHaveBeenCalledWith("無法使用麥克風，請確認瀏覽器權限。"));
    expect(result.current.recording).toBe(false);
  });
});
