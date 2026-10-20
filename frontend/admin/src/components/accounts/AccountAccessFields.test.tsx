import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AccountAccessFields, { type AccountAccessForm } from "./AccountAccessFields";

function formWith(grants: Partial<AccountAccessForm["access"]["grants"]>): AccountAccessForm {
  const access = {
    grants: {
      projects: [],
      avatar_characters: [],
      custom_voices: [],
      avatar_mascots: [],
      avatar_backgrounds: [],
      asr_engines: [],
      ...grants,
    },
    defaults: {
      project_id: "",
      character_id: "",
      voice_provider: "",
      voice_id: "",
      mascot_id: "",
      background_id: "",
    },
    admin_portal_access: false,
    kiosk: false,
  };
  return {
    access,
    complete: false,
    error: null,
    loading: false,
    options: {
      projects: [
        { id: "esg-1", label: "ESG永續" },
        { id: "aws-1", label: "AWS-dev" },
      ],
      avatar_characters: [
        { id: "000", label: "000", visibility: "global" },
        { id: "0713", label: "雀斑", visibility: "project", owner_project_id: "esg-1" },
        { id: "0630", label: "小嘴2", visibility: "project", owner_project_id: "esg-1" },
        { id: "1014", label: "AWS 初階", visibility: "project", owner_project_id: "aws-1" },
      ],
      custom_voices: [
        { id: "hayley", label: "Hayley", provider: "indextts" },
        { id: "Fenrir", label: "Fenrir", provider: "gemini-tts" },
      ],
      avatar_mascots: [],
      avatar_backgrounds: [],
      asr_engines: [{ id: "breeze", label: "Breeze" }],
    },
    reload: vi.fn(),
    setAdminPortalAccess: vi.fn(),
    setKiosk: vi.fn(),
    setDefault: vi.fn(),
    toggle: vi.fn(),
    setSelection: vi.fn(),
  } as unknown as AccountAccessForm;
}

describe("AccountAccessFields 分組", () => {
  it("人物依專案、聲音依引擎分成可收合區段，單一區段的類別不加標題", () => {
    render(<AccountAccessFields form={formWith({})} />);
    expect(screen.getByText("全域（所有專案可用）")).toBeTruthy();
    expect(screen.getByText("專案專屬：ESG永續")).toBeTruthy();
    expect(screen.getByText("專案專屬：AWS-dev")).toBeTruthy();
    expect(screen.getByText("IndexTTS")).toBeTruthy();
    expect(screen.getByText("Gemini TTS")).toBeTruthy();
    // 辨識引擎只有一張清單，沒有區段標題也沒有區段全選。
    expect(screen.queryByRole("button", { name: /全選：Breeze/ })).not.toBeTruthy();
  });

  it("區段的全選只動那個專案的人物，不碰其他專案", () => {
    const form = formWith({ avatar_characters: ["000"] });
    render(<AccountAccessFields form={form} />);
    fireEvent.click(screen.getByRole("button", { name: "全選：專案專屬：ESG永續" }));
    expect(form.setSelection).toHaveBeenCalledWith("avatar_characters", ["000", "0713", "0630"]);
  });

  it("有勾選的區段預設展開，沒勾選的收起", () => {
    render(<AccountAccessFields form={formWith({ avatar_characters: ["1014"] })} />);
    const aws = screen.getByText("專案專屬：AWS-dev").closest("details");
    const esg = screen.getByText("專案專屬：ESG永續").closest("details");
    expect(aws?.hasAttribute("open")).toBe(true);
    expect(esg?.hasAttribute("open")).toBe(false);
    expect(within(aws as HTMLElement).getByText("1 / 1")).toBeTruthy();
  });
});
