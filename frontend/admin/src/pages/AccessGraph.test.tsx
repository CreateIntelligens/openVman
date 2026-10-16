import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchAccountAccessOptions,
  fetchAdminScope,
  listAccounts,
  listTemporaryBatches,
  type Account,
  type TemporaryBatchAudit,
} from "../api/auth";
import { fetchProjectKnowledgeSettings } from "../api/knowledge";
import { fetchProjectPolicy, fetchProjectResources } from "../api/projects";
import { NavigationProvider } from "../context/NavigationContext";
import AccessGraph from "./AccessGraph";

vi.mock("../api/auth", () => ({
  fetchAccountAccessOptions: vi.fn(),
  fetchAdminScope: vi.fn(),
  listAccounts: vi.fn(),
  listTemporaryBatches: vi.fn(),
}));

vi.mock("../api/knowledge", () => ({
  fetchProjectKnowledgeSettings: vi.fn(),
}));

vi.mock("../api/projects", () => ({
  fetchProjectPolicy: vi.fn(),
  fetchProjectResources: vi.fn(),
}));

const batches: TemporaryBatchAudit[] = [
  {
    batch_id: "batch-1",
    created_at: "2026-10-14T06:05:00Z",
    state: "active",
    first_used_at: "2026-10-14T06:10:00Z",
    expires_at: "2026-10-14T14:10:00Z",
    account_count: 2,
    grants: {
      projects: ["p-hk"],
      avatar_characters: ["c-1"],
      custom_voices: ["v-1"],
      asr_engines: [],
    },
    defaults: { project_id: "p-hk", character_id: "c-1", voice_provider: "voxcpm", voice_id: "v-1" },
    accounts: [
      {
        user_id: "t-1", username: "tmp-a1b2", password: "SECRET-PASS-1", state: "active",
        disabled: false, first_used_at: "2026-10-14T06:10:00Z", expires_at: "2026-10-14T14:10:00Z",
        remaining_seconds: 100,
      },
      {
        user_id: "t-2", username: "tmp-c3d4", password: "SECRET-PASS-2", state: "unused",
        disabled: false, first_used_at: null, expires_at: null, remaining_seconds: null,
      },
    ],
    admin_portal_access: false,
    kiosk: true,
  },
];

const accounts: Account[] = [
  {
    id: "root-1",
    username: "ai360",
    role: "root",
    disabled: false,
    created_at: "2026-10-01T00:00:00Z",
    grants: null,
    defaults: null,
  },
  {
    id: "admin-1",
    username: "pm-admin",
    role: "admin",
    disabled: false,
    created_at: "2026-10-01T00:00:00Z",
    grants: null,
    defaults: null,
  },
  {
    id: "user-1",
    username: "clerk",
    role: "user",
    disabled: false,
    created_by: "admin-1",
    admin_portal_access: true,
    created_at: "2026-10-01T00:00:00Z",
    grants: {
      projects: ["p-hk", "p-demo"],
      avatar_characters: ["c-1"],
      custom_voices: ["v-1"],
      asr_engines: [],
    },
    defaults: {
      project_id: "p-hk",
      character_id: "c-1",
      voice_provider: "voxcpm",
      voice_id: "v-1",
    },
  },
  {
    id: "user-2",
    username: "retired",
    role: "user",
    disabled: true,
    created_at: "2026-10-01T00:00:00Z",
    grants: null,
    defaults: null,
  },
];

function renderPage(onSelectTab = vi.fn()) {
  render(
    <NavigationProvider currentTab="Access" currentSubView="graph" onSelectTab={onSelectTab}>
      <AccessGraph />
    </NavigationProvider>,
  );
  return onSelectTab;
}

describe("AccessGraph page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    vi.mocked(listAccounts).mockResolvedValue(accounts);
    vi.mocked(fetchAccountAccessOptions).mockResolvedValue({
      projects: [
        { id: "p-hk", label: "鶴記" },
        { id: "p-demo", label: "展示" },
      ],
      avatar_characters: [{ id: "c-1", label: "小鶴" }],
      custom_voices: [{ id: "v-1", label: "女聲", provider: "voxcpm" }],
      asr_engines: [],
    });
    vi.mocked(fetchAdminScope).mockResolvedValue({
      user_id: "admin-1",
      scoped: true,
      resources: {
        projects: ["p-demo"],
        avatar_characters: [],
        custom_voices: [],
        avatar_mascots: [],
        avatar_backgrounds: [],
      },
    });
    vi.mocked(listTemporaryBatches).mockResolvedValue(batches);
    vi.mocked(fetchProjectKnowledgeSettings).mockImplementation(async (projectId: string) => {
      if (projectId === "p-hk") return { language_routes: ["zh", "nan"] };
      return { language_routes: ["zh"] };
    });
    vi.mocked(fetchProjectPolicy).mockResolvedValue({
      project_id: "p-hk",
      allowed_characters: [],
      allowed_backgrounds: [],
      allowed_mascots: [],
      allowed_tts_voices: [],
      allowed_asr_engines: [],
      default_tts_voice: null,
      default_asr_engine: null,
      taiwanese_asr_engine: null,
      default_character_id: null,
      default_background_id: null,
      default_mascot_id: null,
      updated_by: null,
      updated_at: null,
    });
    vi.mocked(fetchProjectResources).mockResolvedValue({
      avatar_character: [],
      avatar_background: [],
      avatar_mascot: [],
      custom_voice: [],
      asr_engine: [],
      defaults: {
        avatar_character: null,
        avatar_background: null,
        avatar_mascot: null,
        custom_voice: null,
        asr_engine: null,
      },
    });
  });

  it("renders accounts and projects as nodes with a summary", async () => {
    renderPage();

    expect(await screen.findByRole("button", { name: /帳號 clerk/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /帳號 ai360，ROOT，ROOT：全部/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /專案 鶴記/ })).toBeTruthy();
    expect(screen.getByText("4 個帳號 · 2 個專案 · 3 條專案連線")).toBeTruthy();
    expect(fetchAdminScope).toHaveBeenCalledWith("admin-1");
    expect(document.querySelectorAll('[data-edge-kind="scope"]').length).toBe(1);
    expect(document.querySelectorAll('[data-edge-kind="default"]').length).toBe(2);
  });

  it("opens account details on selection and links to account management", async () => {
    const onSelectTab = renderPage();

    const node = await screen.findByRole("button", { name: /帳號 clerk/ });
    fireEvent.keyDown(node, { key: "Enter" });

    const panel = screen.getByRole("complementary", { name: "節點細節" });
    expect(within(panel).getByRole("heading", { name: "clerk" })).toBeTruthy();
    expect(within(panel).getByText("依授權清單")).toBeTruthy();
    expect(within(panel).getByText("可進管理後台")).toBeTruthy();
    expect(within(panel).getByRole("button", { name: /鶴記/ }).textContent).toContain("預設");

    fireEvent.click(within(panel).getByRole("button", { name: /到帳號管理編輯/ }));
    expect(onSelectTab).toHaveBeenCalledWith("Access", "accounts/manage");
  });

  it("finds a project through search and lists who can reach it", async () => {
    renderPage();
    await screen.findByRole("button", { name: /帳號 clerk/ });

    fireEvent.change(screen.getByRole("combobox", { name: "搜尋節點" }), {
      target: { value: "展示" },
    });
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("button", { name: /展示/ }));

    const panel = screen.getByRole("complementary", { name: "節點細節" });
    expect(within(panel).getByRole("heading", { name: "展示" })).toBeTruthy();
    expect(within(panel).getByText("依授權清單（1）")).toBeTruthy();
    expect(within(panel).getByText("依管理範圍（1）")).toBeTruthy();
    expect(within(panel).getByText("ai360")).toBeTruthy();
  });

  it("toggles resource layers and disabled accounts", async () => {
    renderPage();
    await screen.findByRole("button", { name: /帳號 clerk/ });

    expect(screen.queryByRole("button", { name: /聲音 女聲/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^聲音/ }));
    expect(screen.getByRole("button", { name: /聲音 女聲/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^停用帳號/ }));
    expect(screen.queryByRole("button", { name: /帳號 retired/ })).toBeNull();
  });

  it("draws temporary account batches only after the toggle, without passwords", async () => {
    renderPage();
    await screen.findByRole("button", { name: /帳號 clerk/ });

    expect(screen.queryByRole("button", { name: /^臨時帳號 臨時/ })).toBeNull();
    const toggle = screen.getByRole("button", { name: /^臨時批次/ });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(toggle.textContent).toContain("1 批");

    fireEvent.click(toggle);
    const batchNode = screen.getByRole("button", { name: /^臨時帳號 臨時 .*（2），使用中/ });
    expect(screen.getByText(/1 批臨時帳號/)).toBeTruthy();
    fireEvent.keyDown(batchNode, { key: "Enter" });

    const panel = screen.getByRole("complementary", { name: "節點細節" });
    expect(within(panel).getByText("tmp-a1b2")).toBeTruthy();
    expect(within(panel).getByText("未使用")).toBeTruthy();
    expect(within(panel).getByText("展示機台")).toBeTruthy();
    expect(within(panel).getByRole("button", { name: /鶴記/ }).textContent).toContain("預設");
    expect(document.body.textContent).not.toContain("SECRET-PASS");
  });

  it("finds a temporary account by username, marking it while batches are hidden", async () => {
    renderPage();
    await screen.findByRole("button", { name: /帳號 clerk/ });

    const search = screen.getByRole("combobox", { name: "搜尋節點" });
    fireEvent.change(search, { target: { value: "tmp-c3d4" } });
    expect(within(screen.getByRole("listbox")).getByText("已篩掉")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^臨時批次/ }));
    const listbox = screen.getByRole("listbox");
    expect(within(listbox).getByText("臨時帳號")).toBeTruthy();
    expect(within(listbox).queryByText("已篩掉")).toBeNull();
  });

  it("keeps the graph when temporary accounts cannot be read", async () => {
    vi.mocked(listTemporaryBatches).mockRejectedValue(new Error("boom"));
    renderPage();

    await screen.findByRole("button", { name: /帳號 clerk/ });
    const toggle = screen.getByRole("button", { name: /^臨時批次/ }) as HTMLButtonElement;
    expect(toggle.disabled).toBe(true);
    expect(toggle.title).toBe("讀不到臨時帳號");
  });

  it("shows each project's language routes as a badge and in the side panel", async () => {
    vi.mocked(fetchProjectKnowledgeSettings).mockImplementation(async (projectId: string) => {
      if (projectId === "p-hk") return { language_routes: ["zh", "nan"] };
      throw new Error("forbidden");
    });
    renderPage();
    await screen.findByRole("button", { name: /帳號 clerk/ });

    await waitFor(() =>
      expect(document.querySelector("[data-language-badge]")?.textContent).toBe("中·台"),
    );
    expect(fetchProjectKnowledgeSettings).toHaveBeenCalledWith("p-hk");
    expect(fetchProjectKnowledgeSettings).toHaveBeenCalledWith("p-demo");
    expect(document.querySelectorAll("[data-language-badge]").length).toBe(1);

    fireEvent.keyDown(screen.getByRole("button", { name: /專案 鶴記/ }), { key: "Enter" });
    let panel = screen.getByRole("complementary", { name: "節點細節" });
    expect(within(panel).getByText("語言分流")).toBeTruthy();
    expect(within(panel).getByText("台語")).toBeTruthy();
    expect(within(panel).getByText("中文")).toBeTruthy();

    fireEvent.keyDown(screen.getByRole("button", { name: /專案 展示/ }), { key: "Enter" });
    panel = screen.getByRole("complementary", { name: "節點細節" });
    expect(within(panel).getByText("讀不到這個專案的語言分流。")).toBeTruthy();
  });

  it("focuses on a project picked from the project menu and clears it from the chip", async () => {
    renderPage();
    await screen.findByRole("button", { name: /帳號 clerk/ });
    expect(screen.queryByRole("region", { name: "目前的篩選" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "專案" }));
    const dialog = screen.getByRole("dialog", { name: "選擇專案" });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /展示/ }));

    // clerk 有授權、pm-admin 在管理範圍內、ROOT 本來就全部能用；retired 沒有任何授權。
    expect(screen.getByRole("button", { name: /帳號 clerk/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /帳號 pm-admin/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /帳號 ai360/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /帳號 retired/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /專案 鶴記/ })).toBeNull();
    expect(screen.getByText(/篩選後 3 \/ 4 個帳號/)).toBeTruthy();

    const region = screen.getByRole("region", { name: "目前的篩選" });
    expect(within(region).getByText("1 個篩選")).toBeTruthy();
    fireEvent.click(within(region).getByRole("button", { name: "移除篩選：專案：展示" }));

    expect(screen.getByRole("button", { name: /帳號 retired/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /專案 鶴記/ })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "目前的篩選" })).toBeNull();
  });

  it("filters by role and shows an empty state with a clear-all action", async () => {
    renderPage();
    await screen.findByRole("button", { name: /帳號 clerk/ });

    const accountGroup = screen.getByRole("group", { name: "帳號" });
    fireEvent.click(within(accountGroup).getByRole("button", { name: /^ROOT/ }));
    fireEvent.click(within(accountGroup).getByRole("button", { name: /^管理員/ }));
    expect(screen.queryByRole("button", { name: /帳號 ai360/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /帳號 pm-admin/ })).toBeNull();
    expect(screen.getByRole("button", { name: /帳號 clerk/ })).toBeTruthy();
    const region = screen.getByRole("region", { name: "目前的篩選" });
    expect(within(region).getByText("角色：一般帳號")).toBeTruthy();

    fireEvent.click(within(accountGroup).getByRole("button", { name: /^一般帳號/ }));
    const empty = screen.getByRole("status");
    expect(empty.textContent).toContain("沒有帳號符合目前的篩選");
    expect(empty.textContent).toContain("角色：無");

    fireEvent.click(within(empty).getByRole("button", { name: "清除全部篩選" }));
    expect(screen.getByRole("button", { name: /帳號 ai360/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /帳號 pm-admin/ })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "目前的篩選" })).toBeNull();
  });

  it("keeps only default lines when the other relation kinds are off", async () => {
    renderPage();
    await screen.findByRole("button", { name: /帳號 clerk/ });

    const relations = screen.getByRole("group", { name: "連線" });
    fireEvent.click(within(relations).getByRole("button", { name: /^授權/ }));
    fireEvent.click(within(relations).getByRole("button", { name: /^管理範圍/ }));
    fireEvent.click(within(relations).getByRole("button", { name: /^ROOT 指派/ }));

    expect(document.querySelectorAll('[data-edge-kind="scope"]').length).toBe(0);
    expect(document.querySelectorAll('[data-edge-kind="grant"]').length).toBe(0);
    expect(document.querySelectorAll('[data-edge-kind="default"]').length).toBe(2);
    expect(screen.getByRole("button", { name: /帳號 pm-admin/ })).toBeTruthy();
    const region = screen.getByRole("region", { name: "目前的篩選" });
    expect(within(region).getByText("連線：預設")).toBeTruthy();
  });

  it("focuses on a resource from the menu, turning its layer on, and unfocuses from details", async () => {
    renderPage();
    await screen.findByRole("button", { name: /帳號 clerk/ });

    fireEvent.click(screen.getByRole("button", { name: /^資源/ }));
    const dialog = screen.getByRole("dialog", { name: "選擇資源" });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /女聲/ }));

    expect(screen.getByRole("button", { name: /聲音 女聲/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /帳號 pm-admin/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /帳號 retired/ })).toBeNull();
    expect(screen.getByRole("button", { name: /帳號 clerk/ })).toBeTruthy();

    fireEvent.keyDown(screen.getByRole("button", { name: /聲音 女聲/ }), { key: "Enter" });
    const panel = screen.getByRole("complementary", { name: "節點細節" });
    fireEvent.click(within(panel).getByRole("button", { name: /取消聚焦/ }));
    expect(screen.getByRole("button", { name: /帳號 pm-admin/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /聲音 女聲/ })).toBeNull();
  });

  it("restores filters from sessionStorage and saves changes back", async () => {
    window.sessionStorage.setItem(
      "openvman.access-graph.filters",
      JSON.stringify({ projects: ["p-hk", "p-gone"], includeDisabled: false }),
    );
    renderPage();
    await screen.findByRole("button", { name: /帳號 clerk/ });

    const region = screen.getByRole("region", { name: "目前的篩選" });
    expect(within(region).getByText("2 個篩選")).toBeTruthy();
    expect(within(region).getByText("專案：鶴記")).toBeTruthy();
    expect(within(region).getByText("隱藏停用")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /專案 展示/ })).toBeNull();

    fireEvent.click(within(region).getByRole("button", { name: "清除全部" }));
    const saved = JSON.parse(window.sessionStorage.getItem("openvman.access-graph.filters")!);
    expect(saved.projects).toEqual([]);
    expect(saved.includeDisabled).toBe(true);
  });

  it("shows the error when the account list fails", async () => {
    vi.mocked(listAccounts).mockRejectedValue(new Error("這個帳號沒有權限做這件事。"));
    renderPage();

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("沒有權限"));
  });

  it("does not fetch project resources on initial load, but fetches on demand when a project is selected", async () => {
    vi.mocked(fetchProjectResources).mockImplementation(async (projectId: string) => {
      if (projectId === "p-hk") {
        return {
          avatar_character: [],
          avatar_background: [],
          avatar_mascot: [],
          custom_voice: [
            { resource_id: "v-assigned", label: "指派聲音", source: "assigned" },
          ],
          asr_engine: [],
          defaults: {
            avatar_character: null,
            avatar_background: null,
            avatar_mascot: null,
            custom_voice: null,
            asr_engine: null,
          },
        };
      }
      return {
        avatar_character: [],
        avatar_background: [],
        avatar_mascot: [],
        custom_voice: [],
        asr_engine: [],
        defaults: {
          avatar_character: null,
          avatar_background: null,
          avatar_mascot: null,
          custom_voice: null,
          asr_engine: null,
        },
      };
    });

    renderPage();
    await screen.findByRole("button", { name: /帳號 clerk/ });

    // 初始載入只打 policy，不打 resources
    expect(fetchProjectResources).not.toHaveBeenCalled();

    // 點開專案
    const projectNode = screen.getByRole("button", { name: /專案 鶴記/ });
    fireEvent.keyDown(projectNode, { key: "Enter" });

    // 點開後才按需發起 fetchProjectResources
    await waitFor(() => {
      expect(fetchProjectResources).toHaveBeenCalledWith("p-hk");
    });
  });
});
