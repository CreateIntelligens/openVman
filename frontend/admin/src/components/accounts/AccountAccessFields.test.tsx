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

describe("AccountAccessFields 管理員帳號", () => {
  it("管理員不顯示後台勾選，改成說明清單對他不生效", () => {
    render(<AccountAccessFields form={formWith({})} role="admin" />);
    expect(screen.getByRole("note").textContent).toContain("管理員不受這份清單限制");
    expect(screen.queryByLabelText(/允許進入管理後台/)).toBeNull();
  });

  it("一般帳號照舊有後台勾選", () => {
    render(<AccountAccessFields form={formWith({})} role="user" />);
    expect(screen.getByLabelText(/允許進入管理後台/)).toBeTruthy();
    expect(screen.queryByRole("note")).toBeNull();
  });
});

describe("AccountAccessFields 人物預覽", () => {
  it("人物列帶影片第一格預覽，聲音列沒有", () => {
    const { container } = render(<AccountAccessFields form={formWith({ avatar_characters: ["0713"] })} />);
    const videos = Array.from(container.querySelectorAll("video"));
    expect(videos.map((video) => video.getAttribute("src"))).toContain("/static/characters/0713/01.webm");
    expect(videos.every((video) => video.getAttribute("preload") === "metadata")).toBe(true);
    expect(videos.some((video) => (video.getAttribute("src") ?? "").includes("hayley"))).toBe(false);
  });
});

describe("accessFromOptions", () => {
  it("帶回既有的辨識引擎授權，儲存時不會被整份覆蓋掉", async () => {
    const { accessFromOptions } = await import("./AccountAccessFields");
    const options = formWith({}).options!;
    const current = {
      ...formWith({}).access,
      grants: { ...formWith({}).access.grants, asr_engines: ["breeze"] },
    };
    expect(accessFromOptions(options, current).grants.asr_engines).toEqual(["breeze"]);
    // 沒授權過的人不預勾，也不會因為清單有引擎就自動塞一個。
    expect(accessFromOptions(options, undefined).grants.asr_engines).toEqual([]);
  });

  it("辨識引擎區塊不畫登入後預設值", () => {
    render(<AccountAccessFields form={formWith({ asr_engines: ["breeze"] })} />);
    // 只數「預設值」下拉的 label（說明文字也含這幾個字）：專案、2D 人物、VRM、聲音、背景。
    const selects = screen.getAllByText(/^登入後預設值/).filter((node) => node.tagName === "LABEL");
    expect(selects).toHaveLength(5);
  });
});
