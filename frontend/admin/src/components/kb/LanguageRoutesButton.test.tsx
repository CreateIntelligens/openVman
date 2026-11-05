import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LanguageRoutesButton, { lengthTable } from "./LanguageRoutesButton";

const api = vi.hoisted(() => ({
  fetchKnowledgeSettings: vi.fn(),
  saveKnowledgeSettings: vi.fn(),
}));

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, ...api };
});

// 依按鈕的可存取名稱找，手機只留圖示也找得到，不綁顯示文字的 DOM 結構。
const routesButton = (summary: string) => new RegExp(`^回答語言：${summary} · `);

describe("LanguageRoutesButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchKnowledgeSettings.mockResolvedValue({ language_routes: ["zh"] });
    api.saveKnowledgeSettings.mockImplementation(async (settings) => settings);
  });

  it("keeps at least one route but Chinese is not required", async () => {
    render(<LanguageRoutesButton projectId="proj-hospital" />);
    fireEvent.click(await screen.findByRole("button", { name: routesButton("中文") }));

    // 只剩一條時不能取消。
    expect((screen.getByLabelText(/^中文/) as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/^English/));
    await waitFor(() =>
      expect(api.saveKnowledgeSettings).toHaveBeenCalledWith({ language_routes: ["zh", "en"] }),
    );

    // 有兩條之後中文可以取消，只留英文。
    await waitFor(() => expect((screen.getByLabelText(/^中文/) as HTMLInputElement).disabled).toBe(false));
    fireEvent.click(screen.getByLabelText(/^中文/));
    await waitFor(() =>
      expect(api.saveKnowledgeSettings).toHaveBeenLastCalledWith({ language_routes: ["en"] }),
    );
    expect(await screen.findByRole("button", { name: routesButton("English") })).toBeTruthy();
  });

  it("reorders routes so the first one is the primary language", async () => {
    api.fetchKnowledgeSettings.mockResolvedValue({ language_routes: ["zh", "en"] });
    render(<LanguageRoutesButton projectId="proj-hekee" />);
    fireEvent.click(await screen.findByRole("button", { name: routesButton("中文、English") }));

    expect(screen.getByText("主要")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("English 往前移"));
    await waitFor(() =>
      expect(api.saveKnowledgeSettings).toHaveBeenLastCalledWith({ language_routes: ["en", "zh"] }),
    );
    expect(await screen.findByRole("button", { name: routesButton("English、中文") })).toBeTruthy();
  });

  it("saves the reply length in seconds and shows what it means per language", async () => {
    api.fetchKnowledgeSettings.mockResolvedValue({
      language_routes: ["zh", "en"],
      reply_seconds: 20,
      speech_rates: { chars_per_second: 4, words_per_second: 1.5 },
    });
    render(<LanguageRoutesButton projectId="proj-hospital" />);
    fireEvent.click(await screen.findByRole("button", { name: routesButton("中文、English") }));

    const input = screen.getByLabelText("回答長度上限（秒）") as HTMLInputElement;
    expect(input.value).toBe("20");
    fireEvent.change(input, { target: { value: "10" } });
    // 還沒存就先看到換算：10 秒＝中文 40 字、英西 15 個單字。
    expect(screen.getByText("約 40 字")).toBeTruthy();
    expect(screen.getByText("約 15 個單字")).toBeTruthy();
    fireEvent.blur(input);
    await waitFor(() =>
      expect(api.saveKnowledgeSettings).toHaveBeenLastCalledWith({ language_routes: ["zh", "en"], reply_seconds: 10 }),
    );
    expect(await screen.findByRole("button", { name: "回答語言：中文、English · 10 秒" })).toBeTruthy();
  });

  it("zero means unlimited and toggling routes does not resend the seconds", async () => {
    api.fetchKnowledgeSettings.mockResolvedValue({ language_routes: ["zh"], reply_seconds: 0 });
    render(<LanguageRoutesButton projectId="esg" />);
    expect(await screen.findByRole("button", { name: "回答語言：中文 · 長度不限" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: routesButton("中文") }));
    expect(screen.getByText("不限制長度")).toBeTruthy();

    fireEvent.click(screen.getByLabelText(/^English/));
    await waitFor(() =>
      expect(api.saveKnowledgeSettings).toHaveBeenLastCalledWith({ language_routes: ["zh", "en"] }),
    );
  });

  it("closes with Escape and gives the focus back to the button", async () => {
    render(<LanguageRoutesButton projectId="proj-hospital" />);
    const button = await screen.findByRole("button", { name: routesButton("中文") });
    fireEvent.click(button);
    expect(screen.getByRole("dialog", { name: "回答語言設定" })).toBeTruthy();

    fireEvent.keyDown(document.body, { key: "Escape" });

    expect(screen.queryByRole("dialog", { name: "回答語言設定" })).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it("leaves room for the page header so the panel stays on a phone screen", async () => {
    // 手機上面板接在整個頁首下面，375×667 時原本的 14rem 不夠，底部超出畫面 18px。
    render(<LanguageRoutesButton projectId="proj-hospital" />);
    fireEvent.click(await screen.findByRole("button", { name: routesButton("中文") }));

    expect(screen.getByRole("dialog", { name: "回答語言設定" }).className).toContain(
      "max-h-[calc(100dvh-17.5rem)]",
    );
  });

  it("does not listen for Escape while closed", async () => {
    render(<LanguageRoutesButton projectId="proj-hospital" />);
    const button = await screen.findByRole("button", { name: routesButton("中文") });
    (document.activeElement as HTMLElement | null)?.blur?.();

    fireEvent.keyDown(document.body, { key: "Escape" });

    expect(document.activeElement).not.toBe(button);
  });

  it("explains the setting in words on the panel, not in a tooltip", async () => {
    render(<LanguageRoutesButton projectId="proj-hospital" />);
    const button = await screen.findByRole("button", { name: routesButton("中文") });
    expect(button.getAttribute("title")).toBeNull();

    fireEvent.click(button);

    const panel = screen.getByRole("dialog", { name: "回答語言設定" });
    expect(panel.textContent).toContain("訪客用哪種語言問");
    expect(panel.textContent).toContain("至少要勾一種語言");
    expect(panel.textContent).toContain("填 0 就不限制");
    expect(panel.textContent).not.toContain("分流");
    expect(panel.textContent).not.toContain("模型");
  });

  it("rejects seconds out of range without saving", async () => {
    render(<LanguageRoutesButton projectId="proj-hekee" />);
    fireEvent.click(await screen.findByRole("button", { name: routesButton("中文") }));
    const input = screen.getByLabelText("回答長度上限（秒）");
    fireEvent.change(input, { target: { value: "500" } });
    fireEvent.blur(input);
    expect((await screen.findByRole("alert")).textContent).toContain("0 到 120 秒");
    expect(api.saveKnowledgeSettings).not.toHaveBeenCalled();
  });
});

describe("lengthTable", () => {
  it("matches the rates Brain uses in the prompt", () => {
    expect(lengthTable(20, { chars_per_second: 4, words_per_second: 1.5 })).toEqual([
      { label: "中文、台語、日韓", value: "80 字" },
      { label: "English、Español", value: "30 個單字" },
    ]);
  });
});
