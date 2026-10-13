import { fireEvent, render as renderComponent, screen, waitFor, within } from "@testing-library/react";
import { useState, type ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NavigationProvider } from "../context/NavigationContext";
import ModelProviders from "./ModelProviders";
import {
  fetchModelProviderSettings,
  resetModelProviderHealth,
  saveModelProviderSettings,
  type ModelProviderSettings,
  type ProviderHop,
} from "../api/modelProviders";

vi.mock("../api/modelProviders", () => ({
  fetchModelProviderSettings: vi.fn(),
  saveModelProviderSettings: vi.fn(),
  resetModelProviderHealth: vi.fn(),
}));

const hop = (id: string, credential: string, label: string, model: string, enabled = true): ProviderHop => ({
  id, credential_id: credential, label, endpoint: `https://${id}.example/v1`,
  model, default_model: model, model_override: "", enabled, credential_required: true,
  health: { status: "ok" },
});

const settings = (): ModelProviderSettings => ({
  credentials: [
    {
      id: "jev", label: "Jev", environment_variable: "TYPESAFE_API_KEY", used_by: ["決策模型"],
      required: true, configured: true, source: "environment", masked: "••••-key",
    },
    {
      id: "openai", label: "OpenAI", environment_variable: "OPENAI_API_KEY",
      used_by: ["決策模型", "主對話模型"], required: true, configured: false, source: "none", masked: "",
    },
  ],
  categories: [
    {
      id: "decision", label: "決策模型", model_editable: false, configured: true,
      order: ["jev", "openai"], enabled: ["jev", "openai"],
      providers: [hop("jev", "jev", "Jev", "jev-latest"), hop("openai", "openai", "OpenAI Decisions", "gpt-6-luna")],
    },
    {
      id: "chat_llm", label: "主對話模型", model_editable: true, configured: false,
      order: ["gemini", "openai"], enabled: ["gemini"],
      providers: [
        hop("gemini", "gemini", "Gemini", "gemini-3.5-flash-lite"),
        hop("openai", "openai", "OpenAI", "gpt-4.1-mini", false),
      ],
    },
  ],
});

function render(element: ReactElement) {
  function RouteHarness() {
    const [view, setView] = useState<string | undefined>();
    return (
      <NavigationProvider currentTab="ModelProviders" currentSubView={view} onSelectTab={(_tab, next) => setView(next)}>
        {element}
      </NavigationProvider>
    );
  }
  return renderComponent(<RouteHarness />);
}

async function openTab(name: "主對話模型" | "決策模型" | "API 金鑰") {
  fireEvent.click(await screen.findByRole("tab", { name: new RegExp(name) }));
}

describe("ModelProviders", () => {
  beforeEach(() => {
    vi.mocked(fetchModelProviderSettings).mockReset();
    vi.mocked(saveModelProviderSettings).mockReset();
    vi.mocked(fetchModelProviderSettings).mockResolvedValue(settings());
    vi.mocked(saveModelProviderSettings).mockResolvedValue(settings());
  });

  it("shows one category per tab, says which run on deployment defaults, and keeps keys masked", async () => {
    render(<ModelProviders />);

    const chat = await screen.findByTestId("category-chat_llm");
    expect(within(chat).getByText(/尚未在後台儲存過，目前照部署設定運作/)).toBeTruthy();
    expect(screen.getByLabelText("主對話模型 Gemini 模型")).toBeTruthy();
    expect(screen.queryByTestId("category-decision")).toBeNull();
    expect(screen.queryByTestId("credential-jev")).toBeNull();

    await openTab("決策模型");
    expect(within(screen.getByTestId("category-decision")).queryByText(/尚未在後台儲存過/)).toBeNull();
    // 決策模型固定，只有主對話能填模型。
    expect(screen.queryByLabelText("決策模型 Jev 模型")).toBeNull();
    expect(screen.queryByTestId("category-chat_llm")).toBeNull();

    await openTab("API 金鑰");
    expect(screen.getByText(/用於決策模型、主對話模型/)).toBeTruthy();
    expect(screen.getByText(/環境變數已設定/)).toBeTruthy();
  });

  it("keeps edits made on one tab while another tab is open and saves them together", async () => {
    render(<ModelProviders />);

    const openAiRow = await screen.findByTestId("provider-chat_llm-openai");
    fireEvent.click(within(openAiRow).getByLabelText("啟用 主對話模型 OpenAI"));
    expect(screen.getByRole("tab", { name: /主對話模型/ }).querySelector("[aria-label='有未儲存的修改']")).toBeTruthy();
    await openTab("API 金鑰");
    fireEvent.change(screen.getByLabelText("OpenAI API key"), { target: { value: "new-openai-key" } });
    await openTab("主對話模型");
    expect((within(screen.getByTestId("provider-chat_llm-openai")).getByLabelText("啟用 主對話模型 OpenAI") as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "儲存設定" }));

    await waitFor(() => expect(saveModelProviderSettings).toHaveBeenCalled());
    expect(vi.mocked(saveModelProviderSettings).mock.calls[0][0]).toMatchObject({
      categories: { chat_llm: { enabled: ["gemini", "openai"] } },
      credentials: { openai: "new-openai-key" },
    });
  });

  it("saves every category with reordered hops, models and only changed keys", async () => {
    render(<ModelProviders />);

    const openAiRow = await screen.findByTestId("provider-chat_llm-openai");
    fireEvent.click(within(openAiRow).getByRole("button", { name: "上移 主對話模型 OpenAI" }));
    fireEvent.click(within(openAiRow).getByLabelText("啟用 主對話模型 OpenAI"));
    fireEvent.change(within(openAiRow).getByLabelText("主對話模型 OpenAI 模型"), {
      target: { value: "gpt-4.1" },
    });
    await openTab("API 金鑰");
    fireEvent.change(screen.getByLabelText("OpenAI API key"), { target: { value: "new-openai-key" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存設定" }));

    await waitFor(() => expect(saveModelProviderSettings).toHaveBeenCalled());
    expect(vi.mocked(saveModelProviderSettings).mock.calls[0][0]).toEqual({
      categories: {
        chat_llm: {
          order: ["openai", "gemini"],
          enabled: ["openai", "gemini"],
          models: { gemini: "", openai: "gpt-4.1" },
        },
      },
      reset_categories: [],
      credentials: { openai: "new-openai-key" },
      clear_credentials: [],
      use_environment_credentials: [],
    });
  });

  it("saving a decision change leaves the unsaved chat chain on deployment settings", async () => {
    render(<ModelProviders />);

    await openTab("決策模型");
    const openAiRow = await screen.findByTestId("provider-decision-openai");
    fireEvent.click(within(openAiRow).getByRole("button", { name: "上移 決策模型 OpenAI Decisions" }));
    fireEvent.click(screen.getByRole("button", { name: "儲存設定" }));

    await waitFor(() => expect(saveModelProviderSettings).toHaveBeenCalled());
    const body = vi.mocked(saveModelProviderSettings).mock.calls[0][0];
    expect(Object.keys(body.categories)).toEqual(["decision"]);
    expect(body.categories.decision.order).toEqual(["openai", "jev"]);
  });

  it("puts a saved category back on deployment settings", async () => {
    render(<ModelProviders />);

    expect(within(await screen.findByTestId("category-chat_llm")).queryByRole("button", { name: "改回部署設定" })).toBeNull();
    await openTab("決策模型");
    const decision = await screen.findByTestId("category-decision");
    fireEvent.click(within(decision).getByRole("button", { name: "改回部署設定" }));
    expect(within(decision).getByText(/儲存後改回部署設定/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "儲存設定" }));

    await waitFor(() => expect(saveModelProviderSettings).toHaveBeenCalled());
    expect(vi.mocked(saveModelProviderSettings).mock.calls[0][0]).toMatchObject({
      categories: {},
      reset_categories: ["decision"],
    });
  });

  it("warns when a saved key can no longer be decrypted", async () => {
    const result = settings();
    result.credentials[1] = {
      ...result.credentials[1], configured: true, source: "unreadable", masked: "••••-env",
    };
    vi.mocked(fetchModelProviderSettings).mockResolvedValue(result);
    render(<ModelProviders />);

    await openTab("API 金鑰");
    const openai = await screen.findByTestId("credential-openai");
    expect(within(openai).getByText(/無法解密，暫用環境變數/)).toBeTruthy();
    expect(within(openai).getByRole("button", { name: "使用部署預設" })).toBeTruthy();
  });

  it("shows which hops Brain is skipping and why", async () => {
    const result = settings();
    result.categories[0].providers[0].health = { status: "blocked", reason: "http_401", retry_in_seconds: null };
    result.categories[0].providers[1].health = { status: "cooling", reason: "timeout（decision_turn）", retry_in_seconds: 42 };
    vi.mocked(fetchModelProviderSettings).mockResolvedValue(result);
    render(<ModelProviders />);

    expect(within(await screen.findByTestId("provider-chat_llm-gemini")).queryByRole("status")).toBeNull();
    await openTab("決策模型");
    const jev = await screen.findByTestId("provider-decision-jev");
    expect(within(jev).getByRole("status").textContent).toBe("已跳過：金鑰無效，換金鑰後立即重試");
    const openai = screen.getByTestId("provider-decision-openai");
    expect(within(openai).getByRole("status").textContent).toBe("連續失敗，冷卻中，約 42 秒後再試（每輪判斷）");
  });

  it("reports load failures and allows retry", async () => {
    vi.mocked(fetchModelProviderSettings).mockRejectedValueOnce(new Error("讀取失敗"));
    render(<ModelProviders />);

    expect((await screen.findByRole("alert")).textContent).toContain("讀取失敗");
    fireEvent.click(screen.getByRole("button", { name: "重新載入" }));
    await screen.findByTestId("category-chat_llm");
  });

  it("clears a deployment key without sending its value", async () => {
    render(<ModelProviders />);

    await openTab("API 金鑰");
    const jevCredentials = await screen.findByTestId("credential-jev");
    fireEvent.click(within(jevCredentials).getByRole("button", { name: "清除金鑰" }));
    await screen.findByText("將清除目前金鑰");
    fireEvent.click(screen.getByRole("button", { name: "儲存設定" }));

    await waitFor(() => expect(saveModelProviderSettings).toHaveBeenCalled());
    expect(vi.mocked(saveModelProviderSettings).mock.calls[0][0]).toMatchObject({
      clear_credentials: ["jev"],
    });
  });

  it("labels where each key comes from so .env and saved keys do not look the same", async () => {
    const result = settings();
    result.credentials[1] = { ...result.credentials[1], configured: true, source: "admin", masked: "••••abcd" };
    vi.mocked(fetchModelProviderSettings).mockResolvedValue(result);
    render(<ModelProviders />);

    await openTab("API 金鑰");
    expect(within(await screen.findByTestId("credential-jev")).getByText("來自 .env")).toBeTruthy();
    expect(within(screen.getByTestId("credential-openai")).getByText("後台已存（加密）")).toBeTruthy();
  });

  it("says whether Brain picked the change up right away", async () => {
    vi.mocked(saveModelProviderSettings).mockResolvedValue({ ...settings(), runtime_refreshed: true });
    render(<ModelProviders />);

    await screen.findByTestId("category-chat_llm");
    fireEvent.click(screen.getByRole("button", { name: "儲存設定" }));

    expect(await screen.findByText("模型供應商設定已儲存並立即生效。")).toBeTruthy();
  });

  it("resets one failing hop without dropping unsaved edits", async () => {
    const failing = settings();
    failing.categories[1].providers[0].health = { status: "cooling", reason: "timeout（decision_turn）", retry_in_seconds: 30 };
    vi.mocked(fetchModelProviderSettings).mockResolvedValue(failing);
    vi.mocked(resetModelProviderHealth).mockResolvedValue(settings());
    render(<ModelProviders />);

    const openAiRow = await screen.findByTestId("provider-chat_llm-openai");
    fireEvent.click(within(openAiRow).getByLabelText("啟用 主對話模型 OpenAI"));
    fireEvent.click(within(screen.getByTestId("provider-chat_llm-gemini")).getByRole("button", { name: "重置 主對話模型 Gemini 的失敗紀錄" }));

    await waitFor(() => expect(resetModelProviderHealth).toHaveBeenCalledWith({ category: "chat_llm", hop: "gemini" }));
    await waitFor(() => expect(within(screen.getByTestId("provider-chat_llm-gemini")).queryByRole("status")).toBeNull());
    expect((within(screen.getByTestId("provider-chat_llm-openai")).getByLabelText("啟用 主對話模型 OpenAI") as HTMLInputElement).checked).toBe(true);
  });
});
