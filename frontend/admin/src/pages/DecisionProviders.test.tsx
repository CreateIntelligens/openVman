import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DecisionProviders from "./DecisionProviders";
import {
  fetchDecisionProviderSettings,
  saveDecisionProviderSettings,
  type DecisionProviderSettings,
} from "../api/decisionProviders";

vi.mock("../api/decisionProviders", () => ({
  fetchDecisionProviderSettings: vi.fn(),
  saveDecisionProviderSettings: vi.fn(),
}));

const settings = (): DecisionProviderSettings => ({
  order: ["clef-primary", "clef-backup", "jev", "openai"],
  enabled: ["clef-primary", "clef-backup", "jev", "openai"],
  providers: [
    {
      id: "clef-primary", provider: "clef", label: "Clef 主端點",
      endpoint: "https://clef.create360.ai/v1/systemone", model: "clef-flash",
      enabled: true, credential_required: false, credential_configured: false,
      credential_source: "none", credential_masked: "",
    },
    {
      id: "clef-backup", provider: "clef", label: "Clef 備援端點",
      endpoint: "https://clef.aiurl.tw/v1/systemone", model: "clef-flash",
      enabled: true, credential_required: false, credential_configured: false,
      credential_source: "none", credential_masked: "",
    },
    {
      id: "jev", provider: "jev", label: "Jev",
      endpoint: "https://api.typesafe.ai/v1/systemone", model: "jev-latest",
      enabled: true, credential_required: true, credential_configured: true,
      credential_source: "environment", credential_masked: "••••-key",
    },
    {
      id: "openai", provider: "openai", label: "OpenAI Decisions",
      endpoint: "https://api.openai.com/v1/decisions", model: "gpt-6-luna",
      enabled: true, credential_required: true, credential_configured: false,
      credential_source: "none", credential_masked: "",
    },
  ],
});

describe("DecisionProviders", () => {
  beforeEach(() => {
    vi.mocked(fetchDecisionProviderSettings).mockClear();
    vi.mocked(saveDecisionProviderSettings).mockClear();
    vi.mocked(fetchDecisionProviderSettings).mockResolvedValue(settings());
    vi.mocked(saveDecisionProviderSettings).mockResolvedValue(settings());
  });

  it("shows the configured order and keeps keys masked", async () => {
    render(<DecisionProviders />);

    await screen.findByText("Clef 主端點");
    expect(screen.getByText("https://clef.create360.ai/v1/systemone")).toBeTruthy();
    expect(screen.getByText(/環境變數已設定/)).toBeTruthy();
    expect(screen.queryByDisplayValue("env-jev-key")).toBeNull();
  });

  it("saves a human-reordered chain and only sends changed credentials", async () => {
    render(<DecisionProviders />);

    const openAiRow = await screen.findByTestId("provider-openai");
    fireEvent.click(within(openAiRow).getByRole("button", { name: "上移 OpenAI Decisions" }));
    fireEvent.change(screen.getByLabelText("OpenAI API key"), {
      target: { value: "new-openai-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "儲存設定" }));

    await waitFor(() => expect(saveDecisionProviderSettings).toHaveBeenCalled());
    expect(vi.mocked(saveDecisionProviderSettings).mock.calls[0][0]).toMatchObject({
      order: ["clef-primary", "clef-backup", "openai", "jev"],
      credentials: { openai: "new-openai-key" },
    });
  });

  it("reports load failures and allows retry", async () => {
    vi.mocked(fetchDecisionProviderSettings).mockRejectedValueOnce(new Error("讀取失敗"));
    render(<DecisionProviders />);

    expect((await screen.findByRole("alert")).textContent).toContain("讀取失敗");
    fireEvent.click(screen.getByRole("button", { name: "重新載入" }));
    await screen.findByText("Clef 主端點");
  });

  it("lets administrators clear a deployment key without sending its value", async () => {
    render(<DecisionProviders />);

    const jevCredentials = await screen.findByTestId("credential-jev");
    fireEvent.click(within(jevCredentials).getByRole("button", { name: "清除金鑰" }));
    await screen.findByText("將清除目前金鑰");
    fireEvent.click(screen.getByRole("button", { name: "儲存設定" }));

    await waitFor(() => expect(saveDecisionProviderSettings).toHaveBeenCalled());
    expect(vi.mocked(saveDecisionProviderSettings).mock.calls[0][0]).toMatchObject({
      clear_credentials: ["jev"],
    });
    expect(JSON.stringify(vi.mocked(saveDecisionProviderSettings).mock.calls[0][0]))
      .not.toContain("env-jev-key");
  });
});
