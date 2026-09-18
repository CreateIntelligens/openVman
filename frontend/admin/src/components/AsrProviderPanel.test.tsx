import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearAsrProvider,
  fetchAsrProvider,
  setAsrProvider,
  type SystemSetting,
} from "../api/settings";
import AsrProviderPanel from "./AsrProviderPanel";

vi.mock("../api/settings", () => ({
  fetchAsrProvider: vi.fn(),
  setAsrProvider: vi.fn(),
  clearAsrProvider: vi.fn(),
}));

const OPTIONS = ["breeze", "local", "openai", "sensevoice"];

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
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("AsrProviderPanel", () => {
  it("顯示目前生效的引擎與它的實測差異", async () => {
    render(<AsrProviderPanel />);

    expect(await screen.findByText(/SenseVoice-Small/)).toBeTruthy();
    // 選單上只有引擎代號的話，使用者無從判斷該選哪個。
    expect(screen.getByText(/臺語漢字輸出/)).toBeTruthy();
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
