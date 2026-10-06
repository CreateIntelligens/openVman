import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchKnowledgeDocument, fetchKnowledgeSettings, saveKnowledgeDocument } from "../api/knowledge";
import { fetchAsrEngines, previewAsr } from "../api/settings";
import { charErrorRate } from "../utils/charErrorRate";
import AsrProviderPanel from "./AsrProviderPanel";
import { summarizeGlossary } from "./asr/GlossaryEditor";
import { streamTestUrl } from "./asr/StreamTester";
import { streamClip } from "./asr/streamClip";

vi.mock("../api/settings", () => ({ previewAsr: vi.fn(), fetchAsrEngines: vi.fn() }));
vi.mock("../api/knowledge", () => ({
  fetchKnowledgeSettings: vi.fn(),
  fetchKnowledgeDocument: vi.fn(),
  saveKnowledgeDocument: vi.fn(),
}));
vi.mock("../api", () => ({ getActiveProjectId: () => "proj-1" }));
vi.mock("./asr/streamClip", () => ({ streamClip: vi.fn() }));
vi.mock("../hooks/useVad", () => ({
  useVad: () => ({ speaking: false, starting: false, supported: true }),
}));

beforeEach(() => {
  vi.mocked(previewAsr).mockReset();
  vi.mocked(fetchAsrEngines).mockResolvedValue({
    engines: ["breeze", "r2t2", "r2t2-dev", "sensevoice"], stream: ["gemini-live"],
  });
  vi.mocked(streamClip).mockReset();
  vi.mocked(fetchKnowledgeSettings).mockResolvedValue({ language_routes: ["zh", "en", "nan"] });
  vi.mocked(fetchKnowledgeDocument).mockResolvedValue({
    path: "ASR_PROMPT.md", content: "# 鶴記\nDIVA 沉水泵\n常見誤聽：沉睡泵→沉水泵\n",
  } as never);
  vi.mocked(saveKnowledgeDocument).mockResolvedValue({ status: "ok" } as never);
  URL.createObjectURL = vi.fn(() => "blob:clip");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function upload(name = "clip.wav") {
  const clip = new File(["audio"], name, { type: "audio/wav" });
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [clip] } });
  return clip;
}

function engineButton(label: RegExp) {
  return within(screen.getByRole("group", { name: "試辨識的引擎" })).getByRole("button", { name: label });
}

describe("AsrProviderPanel", () => {
  it("讀出專案詞表並分開算詞與誤聽對照", async () => {
    render(<AsrProviderPanel />);
    expect(await screen.findByText("1 個詞・1 條誤聽對照")).toBeTruthy();
    expect(fetchKnowledgeDocument).toHaveBeenCalledWith("ASR_PROMPT.md");
  });

  it("沒建過詞表的專案當成空的，不顯示錯誤", async () => {
    vi.mocked(fetchKnowledgeDocument).mockRejectedValue(new Error("找不到指定文件"));
    render(<AsrProviderPanel />);
    expect(await screen.findByText("0 個詞・0 條誤聽對照")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("改了詞表才能存，存完提醒約一分鐘生效", async () => {
    render(<AsrProviderPanel />);
    const box = await screen.findByLabelText("專案詞表內容");
    const save = screen.getByRole("button", { name: "儲存詞表" }) as HTMLButtonElement;
    await waitFor(() => expect((box as HTMLTextAreaElement).value).toContain("DIVA"));
    expect(save.disabled).toBe(true);

    fireEvent.change(box, { target: { value: "DIVA 沉水泵 EUBL" } });
    fireEvent.click(save);

    await waitFor(() => expect(saveKnowledgeDocument).toHaveBeenCalledWith("ASR_PROMPT.md", "DIVA 沉水泵 EUBL"));
    expect(await screen.findByText("已儲存，約一分鐘內生效。")).toBeTruthy();
  });

  it("同一段音檔同時送給勾的每個引擎，帶專案與分流", async () => {
    vi.mocked(previewAsr)
      .mockResolvedValueOnce({ text: "請問沉水泵", provider: "breeze", elapsed_seconds: 0.8, language_routes: ["zh", "en", "nan"], glossary: "DIVA 沉水泵", language_check: { result: "zh", ms: 900 } })
      .mockResolvedValueOnce({ text: "請問沉睡泵", provider: "r2t2", elapsed_seconds: 0.3, language_routes: ["zh", "en", "nan"], glossary: "DIVA 沉水泵", language_check: { result: "zh", ms: 900 } });
    render(<AsrProviderPanel />);
    await screen.findByRole("button", { name: "台語" });

    fireEvent.click(engineButton(/^Confucius4-R2T2$/));
    const clip = upload();

    await waitFor(() => expect(previewAsr).toHaveBeenCalledTimes(2));
    const context = { projectId: "proj-1", languageRoutes: "zh,en,nan" };
    expect(previewAsr).toHaveBeenNthCalledWith(1, clip, "clip.wav", "breeze", context);
    expect(previewAsr).toHaveBeenNthCalledWith(2, clip, "clip.wav", "r2t2", context);
    expect(await screen.findByText("請問沉水泵")).toBeTruthy();
    expect(await screen.findByText("請問沉睡泵")).toBeTruthy();
    expect(screen.getByText("有套用專案詞表")).toBeTruthy();
    expect(screen.getByText(/台語判斷：不是台語（900 ms）/)).toBeTruthy();
  });

  it("填了參考文字就算錯字率", async () => {
    vi.mocked(previewAsr).mockResolvedValue({ text: "沉睡泵最深可以放多深", provider: "breeze" });
    render(<AsrProviderPanel />);
    fireEvent.change(screen.getByPlaceholderText(/沉水泵最深/), { target: { value: "沉水泵最深可以放多深？" } });
    upload();
    expect(await screen.findByText(/錯字率 10\.0%/)).toBeTruthy();
  });

  it("取消分流會送出剩下的分流，最後一個不能取消", async () => {
    vi.mocked(previewAsr).mockResolvedValue({ text: "hi", provider: "breeze" });
    render(<AsrProviderPanel />);
    const routes = within(await screen.findByRole("group", { name: "語言分流" }));
    await routes.findByRole("button", { name: "台語" });
    fireEvent.click(routes.getByRole("button", { name: "台語" }));
    fireEvent.click(routes.getByRole("button", { name: "English" }));
    expect((routes.getByRole("button", { name: "中文" }) as HTMLButtonElement).disabled).toBe(true);

    upload();
    await waitFor(() => expect(previewAsr).toHaveBeenCalledWith(
      expect.anything(), "clip.wav", "breeze", { projectId: "proj-1", languageRoutes: "zh" },
    ));
  });

  it("指定的引擎沒回應、由備援辨識時講清楚", async () => {
    vi.mocked(previewAsr).mockResolvedValue({ text: "有聽到", provider: "xiaomi" });
    render(<AsrProviderPanel />);
    upload();
    expect(await screen.findByText(/Breeze-ASR-26 沒有回應，這次由 Xiaomi-CocktailASR-1 辨識/)).toBeTruthy();
  });

  it("沒設定的引擎不列出來", async () => {
    vi.mocked(fetchAsrEngines).mockResolvedValue({ engines: ["breeze", "r2t2"], stream: ["r2t2-live"] });
    render(<AsrProviderPanel />);
    await waitFor(() => expect(screen.queryByRole("button", { name: /^SenseVoice-Small$/ })).toBeNull());
    const group = within(screen.getByRole("group", { name: "試辨識的引擎" }));
    expect(group.getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Breeze-ASR-26", "Confucius4-R2T2", "Confucius4-R2T2 串流",
    ]);
  });

  it("不等前一家回來就送下一家", async () => {
    let release: () => void = () => {};
    vi.mocked(previewAsr)
      .mockImplementationOnce(() => new Promise((resolve) => {
        release = () => resolve({ text: "慢", provider: "breeze" });
      }))
      .mockResolvedValueOnce({ text: "快", provider: "r2t2" });
    render(<AsrProviderPanel />);
    fireEvent.click(await waitFor(() => engineButton(/^Confucius4-R2T2$/)));
    upload();

    await waitFor(() => expect(previewAsr).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("快")).toBeTruthy();
    release();
    expect(await screen.findByText("慢")).toBeTruthy();
  });

  it("收音一律走 VAD，沒有另外的自動斷句開關", async () => {
    render(<AsrProviderPanel />);
    expect(await screen.findByRole("button", { name: "開始講話" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "自動斷句" })).toBeNull();
    expect(screen.queryByRole("button", { name: "錄一段" })).toBeNull();
  });

  it("之後再勾的引擎直接拿畫面上的音檔跑，不用重傳", async () => {
    vi.mocked(previewAsr)
      .mockResolvedValueOnce({ text: "第一家", provider: "breeze" })
      .mockResolvedValueOnce({ text: "後來勾的", provider: "r2t2" });
    render(<AsrProviderPanel />);
    const clip = upload();
    expect(await screen.findByText("第一家")).toBeTruthy();

    fireEvent.click(engineButton(/^Confucius4-R2T2$/));

    expect(await screen.findByText("後來勾的")).toBeTruthy();
    expect(previewAsr).toHaveBeenLastCalledWith(clip, "clip.wav", "r2t2", expect.anything());
    // 取消再勾回來直接顯示，不重跑。
    fireEvent.click(engineButton(/^Confucius4-R2T2$/));
    fireEvent.click(engineButton(/^Confucius4-R2T2$/));
    expect(previewAsr).toHaveBeenCalledTimes(2);
  });

  it("重跑用同一段音檔再送一次", async () => {
    vi.mocked(previewAsr)
      .mockResolvedValueOnce({ text: "舊的", provider: "breeze" })
      .mockResolvedValueOnce({ text: "新的", provider: "breeze" });
    render(<AsrProviderPanel />);
    upload();
    expect(await screen.findByText("舊的")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "clip.wav 重跑" }));
    expect(await screen.findByText("新的")).toBeTruthy();
    expect(screen.queryByText("舊的")).toBeNull();
  });

  it("串流引擎把同一段音檔整段送進串流端點", async () => {
    vi.mocked(previewAsr).mockResolvedValue({ text: "批次", provider: "breeze" });
    vi.mocked(streamClip).mockResolvedValue({ text: "串流聽到的", elapsedSeconds: 0.6 });
    render(<AsrProviderPanel />);
    fireEvent.click(await waitFor(() => engineButton(/^Gemini Live$/)));
    const clip = upload();

    expect(await screen.findByText("串流聽到的")).toBeTruthy();
    const [url, sent] = vi.mocked(streamClip).mock.calls[0];
    expect(new URL(url).searchParams.get("engine")).toBe("gemini-live");
    expect(new URL(url).searchParams.get("language_routes")).toBe("zh,en,nan");
    expect(sent).toBe(clip);
    // Gemini 不會自己關線，只能等靜下來。
    expect(vi.mocked(streamClip).mock.calls[0][2]).toMatchObject({ waitForClose: false, speed: 4 });
    expect(screen.getByText(/0\.60 秒（4 倍速送）/)).toBeTruthy();
  });

  it("同一台機器的批次和串流依序送，R2T2 串流等關線才收", async () => {
    vi.mocked(fetchAsrEngines).mockResolvedValue({ engines: ["breeze", "r2t2"], stream: ["r2t2-live"] });
    let releaseBatch: () => void = () => {};
    vi.mocked(previewAsr).mockImplementation((_clip, _name, engine) => (engine === "r2t2"
      ? new Promise((resolve) => { releaseBatch = () => resolve({ text: "批次好了", provider: "r2t2" }); })
      : Promise.resolve({ text: "Breeze 好了", provider: "breeze" })));
    vi.mocked(streamClip).mockResolvedValue({ text: "串流好了", elapsedSeconds: 0.2 });
    render(<AsrProviderPanel />);
    fireEvent.click(await waitFor(() => engineButton(/^Confucius4-R2T2$/)));
    fireEvent.click(engineButton(/^Confucius4-R2T2 串流$/));
    upload();

    // 不同機器同時送：Breeze 不用等。
    expect(await screen.findByText("Breeze 好了")).toBeTruthy();
    expect(streamClip).not.toHaveBeenCalled();
    releaseBatch();
    expect(await screen.findByText("串流好了")).toBeTruthy();
    expect(vi.mocked(streamClip).mock.calls[0][2]).toMatchObject({ waitForClose: true, speed: 4 });
  });

  it("串流引擎邊辨識邊顯示目前聽到的字", async () => {
    vi.mocked(previewAsr).mockResolvedValue({ text: "批次", provider: "breeze" });
    let finish: () => void = () => {};
    vi.mocked(streamClip).mockImplementation((_url, _clip, options) => new Promise((resolve) => {
      options?.onPartial?.("我有一支");
      finish = () => resolve({ text: "我有一支槍", elapsedSeconds: 0.1 });
    }));
    render(<AsrProviderPanel />);
    fireEvent.click(await waitFor(() => engineButton(/^Gemini Live$/)));
    upload();

    expect(await screen.findByText("我有一支")).toBeTruthy();
    finish();
    expect(await screen.findByText("我有一支槍")).toBeTruthy();
  });

  it("一個引擎都沒勾就不送", async () => {
    render(<AsrProviderPanel />);
    fireEvent.click(engineButton(/^Breeze-ASR-26$/));
    upload();
    expect(await screen.findByText("至少勾一個引擎。")).toBeTruthy();
    expect(previewAsr).not.toHaveBeenCalled();
  });
});

describe("串流試聽網址", () => {
  it("帶管理員指定的引擎、專案與分流", () => {
    const url = new URL(streamTestUrl("r2t2-dev-live", "proj-1", ["zh", "es"]));
    expect(url.pathname).toBe("/api/v1/asr/stream");
    expect(url.searchParams.get("engine")).toBe("r2t2-dev-live");
    expect(url.searchParams.get("project_id")).toBe("proj-1");
    expect(url.searchParams.get("language_routes")).toBe("zh,es");
  });
});

describe("錯字率", () => {
  it("跟 voice_e2e 一樣不計大小寫、標點、異體字", () => {
    expect(charErrorRate("請問 DIVA 有攪拌器嗎？", "請問diva有攪拌器嗎?")).toBe(0);
    expect(charErrorRate("HIPPO 污水泵", "HIPPO汙水泵")).toBe(0);
    expect(charErrorRate("沉水泵最深可以放多深", "沉睡泵最深可以放多深")).toBeCloseTo(0.1);
    expect(charErrorRate("沉水泵", "")).toBe(1);
  });
});

describe("詞表統計", () => {
  it("說明行不算，誤聽對照另外算", () => {
    expect(summarizeGlossary("# 說明\n＃全形說明\nDIVA\n\n沉睡泵->沉水泵")).toEqual({ terms: 1, mappings: 1 });
  });
});
