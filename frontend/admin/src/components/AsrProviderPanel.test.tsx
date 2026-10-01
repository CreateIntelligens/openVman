import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { previewAsr } from "../api/settings";
import AsrProviderPanel from "./AsrProviderPanel";

vi.mock("../api/settings", () => ({
  previewAsr: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(previewAsr).mockReset();
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function upload(name = "clip.wav") {
  const clip = new File(["audio"], name, { type: "audio/wav" });
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [clip] } });
  return clip;
}

describe("AsrProviderPanel", () => {
  it("沒有全站預設引擎可以改，只剩試辨識", () => {
    render(<AsrProviderPanel />);

    expect(screen.queryByText("預設語音辨識引擎")).toBeNull();
    expect(screen.queryByRole("button", { name: "改回部署設定" })).toBeNull();
    expect(screen.getByText("試辨識")).toBeTruthy();
  });

  it("選單列出伺服器引擎並顯示說明", async () => {
    render(<AsrProviderPanel />);

    fireEvent.click(screen.getByRole("combobox", { name: "試辨識的引擎" }));
    const labels = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(labels).toEqual([
      "Breeze-ASR-26", "Confucius4-R2T2", "Xiaomi-CocktailASR-1", "SenseVoice-Small", "OpenAI Whisper",
    ]);
    // 選單上只有引擎代號的話，使用者無從判斷該選哪個。
    fireEvent.mouseDown(screen.getByRole("option", { name: /SenseVoice-Small/ }));
    expect(screen.getAllByText(/臺語漢字輸出/).length).toBeGreaterThan(0);
  });

  it("用選的引擎試辨識", async () => {
    vi.mocked(previewAsr).mockResolvedValue({ text: "今仔日天氣袂歹", provider: "sensevoice" });
    render(<AsrProviderPanel />);

    fireEvent.click(screen.getByRole("combobox", { name: "試辨識的引擎" }));
    fireEvent.mouseDown(await screen.findByRole("option", { name: /SenseVoice-Small/ }));
    const clip = upload();

    await waitFor(() => expect(previewAsr).toHaveBeenCalledWith(clip, "clip.wav", "sensevoice"));
    expect(await screen.findByText("今仔日天氣袂歹")).toBeTruthy();
    expect(screen.queryByText(/這次由/)).toBeNull();
  });

  it("指定的引擎沒回應、由備援辨識時講清楚", async () => {
    vi.mocked(previewAsr).mockResolvedValue({ text: "有聽到", provider: "xiaomi" });
    render(<AsrProviderPanel />);
    upload();

    expect(await screen.findByText(/Breeze-ASR-26 沒有回應，這次由 Xiaomi-CocktailASR-1 辨識/)).toBeTruthy();
  });

  it("上傳音檔就送辨識，不必先錄音", async () => {
    // 同一個檔案切換引擎再試一次才能客觀比較，重錄每次都是不同輸入。
    vi.mocked(previewAsr).mockResolvedValue({
      text: "今仔日天氣袂歹", provider: "sensevoice",
    });
    render(<AsrProviderPanel />);

    const clip = new File(["audio"], "clip.wav", { type: "audio/wav" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [clip] } });

    // 檔名要一起送：後端拿副檔名決定怎麼解這個檔，mp3 冠上 .webm 會轉檔失敗。
    await waitFor(() => expect(previewAsr).toHaveBeenCalledWith(clip, "clip.wav", "breeze"));
    expect(await screen.findByText("今仔日天氣袂歹")).toBeTruthy();
  });

  it("清空 input 不能把選到的檔案一起清掉", async () => {
    // 真實的 <input type=file> 一旦把 value 設成 ""，files 也會跟著變空。
    // 先清再讀就永遠讀不到檔案，畫面只會說「未選擇任何檔案」。
    vi.mocked(previewAsr).mockResolvedValue({ text: "有聽到", provider: "breeze" });
    render(<AsrProviderPanel />);

    const clip = new File(["audio"], "clip.mp3", { type: "audio/mpeg" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    let files: File[] = [clip];
    Object.defineProperty(input, "files", { get: () => files, configurable: true });
    Object.defineProperty(input, "value", {
      get: () => (files.length ? "C:\\fakepath\\clip.mp3" : ""),
      set: () => { files = []; },
      configurable: true,
    });
    fireEvent.change(input);

    await waitFor(() => expect(previewAsr).toHaveBeenCalledWith(clip, "clip.mp3", "breeze"));
  });

  it("上傳辨識失敗時顯示錯誤", async () => {
    vi.mocked(previewAsr).mockRejectedValue(new Error("音檔超過大小限制"));
    render(<AsrProviderPanel />);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "big.wav", { type: "audio/wav" })] },
    });

    await waitFor(() => expect(
      screen.getByRole("alert").textContent,
    ).toContain("音檔超過大小限制"));
  });

});
