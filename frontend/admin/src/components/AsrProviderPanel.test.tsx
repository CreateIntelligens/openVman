import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearAsrProvider,
  fetchAsrProvider,
  previewAsr,
  setAsrProvider,
  type SystemSetting,
} from "../api/settings";
import AsrProviderPanel from "./AsrProviderPanel";

vi.mock("../api/settings", () => ({
  fetchAsrProvider: vi.fn(),
  setAsrProvider: vi.fn(),
  clearAsrProvider: vi.fn(),
  previewAsr: vi.fn(),
}));

const OPTIONS = ["breeze", "openai", "sensevoice", "xiaomi"];

function setting(overrides: Partial<SystemSetting> = {}): SystemSetting {
  return {
    key: "asr_provider",
    value: "",
    effective: "sensevoice",
    overridden: false,
    options: OPTIONS,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(fetchAsrProvider).mockReset().mockResolvedValue(setting());
  vi.mocked(setAsrProvider).mockReset();
  vi.mocked(clearAsrProvider).mockReset();
  vi.mocked(previewAsr).mockReset();
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("AsrProviderPanel", () => {
  it("顯示目前生效的引擎與它的實測差異", async () => {
    render(<AsrProviderPanel />);

    expect(await screen.findByText(/SenseVoice-Small/)).toBeTruthy();
    // 選單上只有引擎代號的話，使用者無從判斷該選哪個。
    expect(screen.getByText(/臺語漢字輸出/)).toBeTruthy();
  });

  it("新加的引擎也要有說明，不能只出現代號", async () => {
    vi.mocked(fetchAsrProvider).mockResolvedValue(setting({ effective: "xiaomi" }));
    render(<AsrProviderPanel />);

    expect(await screen.findByText(/Xiaomi-CocktailASR-1/)).toBeTruthy();
    expect(screen.getByText(/自動轉繁/)).toBeTruthy();
  });

  it("沿用部署設定時不顯示還原按鈕", async () => {
    render(<AsrProviderPanel />);

    expect(await screen.findByText(/沿用部署設定/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "改回部署設定" })).toBeNull();
  });

  it("被覆寫時才顯示還原按鈕，並能改回部署設定", async () => {
    vi.mocked(fetchAsrProvider).mockResolvedValue(
      setting({ value: "breeze", effective: "breeze", overridden: true }),
    );
    vi.mocked(clearAsrProvider).mockResolvedValue(setting());
    render(<AsrProviderPanel />);

    const restore = await screen.findByRole("button", { name: "改回部署設定" });
    fireEvent.click(restore);

    await waitFor(() => expect(clearAsrProvider).toHaveBeenCalled());
    expect(await screen.findByText(/已改回部署設定/)).toBeTruthy();
  });

  it("上傳音檔就送辨識，不必先錄音", async () => {
    // 同一個檔案切換引擎再試一次才能客觀比較，重錄每次都是不同輸入。
    vi.mocked(previewAsr).mockResolvedValue({
      text: "今仔日天氣袂歹", provider: "sensevoice",
    });
    render(<AsrProviderPanel />);
    await screen.findByText(/SenseVoice-Small/);

    const clip = new File(["audio"], "clip.wav", { type: "audio/wav" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [clip] } });

    // 檔名要一起送：後端拿副檔名決定怎麼解這個檔，mp3 冠上 .webm 會轉檔失敗。
    await waitFor(() => expect(previewAsr).toHaveBeenCalledWith(clip, "clip.wav"));
    expect(await screen.findByText("今仔日天氣袂歹")).toBeTruthy();
  });

  it("清空 input 不能把選到的檔案一起清掉", async () => {
    // 真實的 <input type=file> 一旦把 value 設成 ""，files 也會跟著變空。
    // 先清再讀就永遠讀不到檔案，畫面只會說「未選擇任何檔案」。
    vi.mocked(previewAsr).mockResolvedValue({ text: "有聽到", provider: "breeze" });
    render(<AsrProviderPanel />);
    await screen.findByText(/SenseVoice-Small/);

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

    await waitFor(() => expect(previewAsr).toHaveBeenCalledWith(clip, "clip.mp3"));
  });

  it("上傳辨識失敗時顯示錯誤", async () => {
    vi.mocked(previewAsr).mockRejectedValue(new Error("音檔超過大小限制"));
    render(<AsrProviderPanel />);
    await screen.findByText(/SenseVoice-Small/);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "big.wav", { type: "audio/wav" })] },
    });

    await waitFor(() => expect(
      screen.getByRole("alert").textContent,
    ).toContain("音檔超過大小限制"));
  });

  it("載入失敗時說明原因，不是留一個空面板", async () => {
    vi.mocked(fetchAsrProvider).mockRejectedValue(new Error("boom"));
    render(<AsrProviderPanel />);

    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      expect.stringContaining("無法載入"),
    );
  });

  it("選了另一個引擎就送出，不用再按儲存", async () => {
    vi.mocked(setAsrProvider).mockResolvedValue(
      setting({ value: "breeze", effective: "breeze", overridden: true }),
    );
    render(<AsrProviderPanel />);
    await screen.findByText(/SenseVoice-Small/);

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.mouseDown(await screen.findByRole("option", { name: /Breeze-ASR-26/ }));

    await waitFor(() => expect(setAsrProvider).toHaveBeenCalledWith("breeze"));
    expect(await screen.findByText(/已改用 Breeze-ASR-26/)).toBeTruthy();
  });

  it("儲存失敗時顯示後端的訊息", async () => {
    vi.mocked(setAsrProvider).mockRejectedValue(new Error("不是允許的值"));
    render(<AsrProviderPanel />);
    await screen.findByText(/SenseVoice-Small/);

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.mouseDown(await screen.findByRole("option", { name: /Breeze-ASR-26/ }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("不是允許的值"));
  });
});
